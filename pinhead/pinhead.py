#!/usr/bin/python2.7
import sys
import os
import subprocess
import libvirt
from operator import itemgetter
import logging
import logging.handlers


def vCPUInfo():
	''' This gathers info about vCPU requirements of currently running domains by querying libvirt and counting active vcpus. '''

	runningDomsIDs = conn.listDomainsID()

	domvCPUs = {}
	
	for runningDomID in runningDomsIDs:
		runningDom = conn.lookupByID(runningDomID)
		#runningDomInfo = runningDom.info()
		#runningDomvCPUs = runningDomInfo[3] # number of vcpus is always in position 3
		vmCPUInfo = runningDom.vcpus()[0] # something like [(0, 1, 405400000000L, 5), (1, 1, 142000000000L, 13), (2, 1, 208550000000L, 7), (3, 1, 111900000000L, 15)]
		runningDomvCPUs = 0
		for vCPU in vmCPUInfo:
			if vCPU[1] == 1: runningDomvCPUs += 1 # only count actually running vCPUs

		#print "Domain %d has %d vCPUs" % (runningDomID, runningDomvCPUs)
		domvCPUs[runningDomID] = runningDomvCPUs # add to collection of domains with their vCPUs

	# get a list of (domain ID, domain vCPUs) pairs sorted by descending number of vCPUs
	domsSortedbyvCPUs = sorted(domvCPUs.items(), key=itemgetter(1), reverse = True)
	
	''' We now have a structure that holds vcpu allocation requests for currently running domains.
	It is a sorted list of tuples (runningDomID, number of vcpus). e.g.: [(7, 4), (8, 2), (9, 2), (10, 1)].	'''

	return domsSortedbyvCPUs

def pCPUInfo():
	''' This gathers info about current configuration of local sockets/cpus/cores/threads.
	Doing this via libvirt yields inconsistent results, so we do it by examining the output of lscpu.
	Different implementations of lscpu might require additional configuration for successful detection of the values. '''

	lscpu = subprocess.check_output(['lscpu'])

	for line in lscpu.split("\n"):
		if line.startswith('CPU(s):'):
			cpus = int(line.split(":")[1].strip())
		elif 'Thread(s) per core:' in line:
			threadsPerCore = int(line.split(":")[1].strip())
		elif 'Core(s) per socket:' in line:
			coresPerSocket = int(line.split(":")[1].strip())
		elif ('Socket(s):' in line) or ('CPU socket(s):' in line):
			sockets = int(line.split(":")[1].strip())
	
	if not (cpus * threadsPerCore * coresPerSocket * sockets):
		log.info('Failed to collect meaningful information about physical CPUs. Exiting')
		sys.exit(1)

	#print "%d cpus, %d threadsPerCore, %d coresPerSocket, %d sockets" % (cpus, threadsPerCore, coresPerSocket, sockets)
	
	cpuTree=[[[['s'+str(k)+'c'+str(i)+'t'+str(j), None, []] for j in range(0, threadsPerCore)] for i in range(0, coresPerSocket)] for k in range(0, sockets)]

	''' We now have a cpuTree structure made of nested lists. The hierarchy goes: cpuTree -> sockets -> cores -> threads.
	E.g. for a 2x4x2 configuration, as detected above:
	
	cpuTree = [
		[ this is a socket
			[['s0c0t0', None, []], ['s0c0t1', None, []]], this is a core, with its threads
			[['s0c1t0', None, []], ['s0c1t1', None, []]],
			[['s0c2t0', None, []], ['s0c2t1', None, []]],
			[['s0c3t0', None, []], ['s0c3t1', None, []]]
		],
		[
			[['s1c0t0', None, []], ['s1c0t1', None, []]], 
			[['s1c1t0', None, []], ['s1c1t1', None, []]], 
			[['s1c2t0', None, []], ['s1c2t1', None, []]], 
			[['s1c3t0', None, []], ['s1c3t1', None, []]]
		]
	]
	
	Each thread element (e.g. ['s1c2t0', None, []]) contains:
	[our id string, Linux cpu id (init. to None), list of vms pinned to it (init. to an empty list)] '''

	# now we map /sys/devices/system/cpu/cpu## devices in Linux to the cpuTree by using their processor topology
	for cpu in range(0, cpus):
		physical_package_id = open('/sys/devices/system/cpu/cpu' + str(cpu) + '/topology/physical_package_id', 'r').read().strip()
		core_id = open('/sys/devices/system/cpu/cpu' + str(cpu) + '/topology/core_id', 'r').read().strip()

		# look for a suitable match in the cpuTree
		for socket in cpuTree:
			for core in socket:
				for thread in core:
					if thread[0].startswith('s' + physical_package_id + 'c' + core_id):
						# match found. try to map cpu## to second slot in the structure
						if thread[1] is None:
							thread[1] = 'cpu' + str(cpu) # mapped to the correct /sys/devices/system/cpu/cpu##
							#print thread[0], ' -> ', thread[1]
							#print cpuTree
							break # stop now, or the cpu will be assigned more than once
	
	return cpuTree


def deviseAndApplyStrategy():
	''' We follow an allocation strategy based on the physical processor information gathered from the system
	and the vcpu requirements gathered via libvirt. We walk down the vCPUInfo list, starting with the vm with the most vcpus required,
	and pin each vm's vcpus to physical cpus. example scenarios:
	8+ vcpus: pin to a 4x(free core + ht), on same socket if possible
	4 cpus: : pin to a 2x(free core + ht), on same socket if possible
	2 vcpus: pin to a free core + ht on the freest socket (or two cores on the same socket if no ht)
	1 vcpu: pin to a free core on the freest socket, don't use ht: only use it if we don't have free cores left. '''

	for vm in vInfo:
		vmID = vm[0]
		vcpus = vm[1]
		log.info("vm id %d has %d vcpus." % (vmID, vcpus))
		
		# get a list of sockets in current load order (lightest first)
		sortedSockets = getSocketsSortedByLoad()
		# print "available sockets: ", sortedSockets
		
		# pass the list to the free(st) thread finder function
		sortedThreads = getThreadsForAllocation(sortedSockets, vcpus)
		
		# do the allocation (this updates the cpuTree with allocation information)
		doAllocation(sortedThreads, vmID)
		
		# do the pinning
		doPinning(vmID)


def getSocketsSortedByLoad():
	''' Find and return a list of the best sockets in pInfo for allocation of vms. '''

	curSocket = 0
	loadForSocket = {} # this keeps track of the load for each socket[0], [1], etc (as many as in pInfo)
	for socket in pInfo:
		loadForSocket[curSocket] = 0
		for core in socket:
			for thread in core: # the third element is the list of currently allocated vms (i.e. pinned vcpus) to this thread
				loadForSocket[curSocket] += len(thread[2])
		
		#print "load for socket %d is %d" % (curSocket, loadForSocket[curSocket])
		curSocket += 1
	
	# sort the dictionary, lightest load first
	loadForSocketSorted = sorted(loadForSocket.items(), key=itemgetter(1))
	return loadForSocketSorted


def getThreadsForAllocation(sortedSockets, numOfvCPUs):
	''' From the given list of sockets (already sorted by load) get the #numOfvCPUs best threads for allocating the virtual cpus.
	sortedSockets looks like: [(1, 0) (0, 1) (2, 1) (3, 4)], a list of (socket number, load).
	We run down the list and fetch the threads until we have assigned all vcpus. '''

	assignedCPUs = 0
	assignedThreads = []
	
	# get list of eligible full cores from socket
	for curSocket in sortedSockets:
		socketWeAreExamining = curSocket[0]
		freestCores = getFreestCores(socketWeAreExamining)
		
		''' freestCores now looks like: [(1, 0) (0, 1)], a list of (local (to the cpu) core number, load)
		Get into that core list and start assigning cpus. '''
		for core in freestCores:
			coreN = core[0]
			# find threads available in that core
			threads = pInfo[socketWeAreExamining][coreN]
			for thread in threads:
				assignedThreads.append(thread)
				assignedCPUs += 1
				#print "assigned thread ", thread, " (", assignedCPUs, " out of ", numOfvCPUs , " assigned)"
				# check if we are done
				if assignedCPUs == numOfvCPUs: break
			if assignedCPUs == numOfvCPUs: break
		if assignedCPUs == numOfvCPUs: break
	
	# what if we run out of sockets? FIXME
	if assignedCPUs < numOfvCPUs:
		log.info("insufficient threads (need %d); allocation incomplete" % (numOfvCPUs))

	return assignedThreads


def getFreestCores(socket):
	''' This finds the single best available core/pair of threads in socket. '''

	curCore = 0
	loadForCore = {} # this keeps track of the load for each core[0], [1], etc.
	for core in pInfo[socket]:
		loadForCore[curCore] = 0
		for thread in core: # the third element is the list of currently allocated vms (i.e. pinned vcpus) to this thread
			loadForCore[curCore] += len(thread[2])
		#print "load for core %d is %d" % (curCore, loadForCore[curCore])
		curCore += 1

	# sort the dictionary and get the core with the lightest load first
	loadForCoreSorted = sorted(loadForCore.items(), key=itemgetter(1))
	return loadForCoreSorted


def doAllocation(chosenThreads, vmID):
	#print "allocating vm %d to threads " % (vmID), chosenThreads
	
	for thread in chosenThreads:
		# save the pinning info to pInfo
		#print "allocating vm %d to thread %s (linux %s)" % (vmID, thread[0], thread[1])
		thread[2].append(vmID)


def doPinning(vmID):
	''' This does the actual pinning. We walk down pInfo looking for a thread with this vmID in thread[2] (among other ones)
	and make a list of vcpu number -> linux cpu mappings. '''

	pinMappings = []
	vm = conn.lookupByID(vmID)
	vmCPUInfo = vm.vcpus()[0] # something like [(0, 1, 405400000000L, 5), (1, 1, 142000000000L, 13), (2, 1, 208550000000L, 7), (3, 1, 111900000000L, 15)]
	vCPUBeingPinnedPosition = 0 # the position inside vmCPUInfo of the vCPU about to be pinned. we increment the position to move down the list and read the vCPU number
	
	for socket in pInfo:
		for core in socket:
			for thread in core:
				if vmID in thread[2]:
					# one vcpu from this vm needs to be pinned to this thread (linux cpu is in thread[1])
					vCPUNumber = vmCPUInfo[vCPUBeingPinnedPosition][0]
					log.info("pinning vm %d (vCPU %d) to thread %s (linux %s)" % (vmID, vCPUNumber, thread[0], thread[1]))
					pinMappings.append([vCPUNumber, thread[1]])
					vCPUBeingPinnedPosition += 1 # or we could use a pop/stack system
	
	for pinMapping in pinMappings:
		''' First we need to make a list of True/False values, one for each linux CPU.
		All False except for the specific CPU we are pinning to. '''

		pinMask = []

		for socket in pInfo:
			for core in socket:
				for thread in core:
					pinMask.append(False) # pinMask initialized with the correct number of slots
		
		posOfCPUinMask = int(pinMapping[1][3:]) # get the position in the pin mask based on the linux cpu name (take out 'cpu' first)
		pinMask[posOfCPUinMask] = True # pin mask updated with the pinning for this vCPU/CPU combo
		pinMask = tuple(pinMask) # api call requires a tuple, not a list
		pinnablevCPU = pinMapping[0]
		#print pinnablevCPU, pinMask
		vm.pinVcpu(pinnablevCPU, pinMask)

	
	'''https://www.redhat.com/archives/libvirt-users/2010-September/msg00073.html
	domain.pinVcpu(1, (False, False, True, False, True, False....[and so on til I have 16 things]))
	In other words, pinVcpu accepts as arguments the vCPU that I wish to act on,
	and a 16 (or however many CPU's are present on the host) item tuple of True/False values,
	in the same order as the CPU's I wish to mask (for example, item 0 of the tuple represents CPU0),
	True meaning that the vCPU thread is allowed to run there, and False meaning that it is not.'''


if __name__ == "__main__":
	
	# set up logging
	
	log = logging.getLogger(__name__)
	log.setLevel(logging.INFO)
	handler = logging.handlers.SysLogHandler(address = '/dev/log')
	formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
	handler.setFormatter(formatter)
	log.addHandler(handler)

	# Set up connection to kvm
	conn = libvirt.open('qemu:///system')
	if conn == None:
		log.info('Failed to open connection to the hypervisor. Exiting')
		sys.exit(1)
	
	# Populate global objects with necessary information
	vInfo = vCPUInfo()
	pInfo = pCPUInfo()

	# for testing:
	#pInfo = [[[['s0c0t0', 'cpu1', []], ['s0c0t1', 'cpu9', []]], [['s0c1t0', 'cpu3', []], ['s0c1t1', 'cpu11', []]], [['s0c2t0', 'cpu5', []], ['s0c2t1', 'cpu13', []]], [['s0c3t0', 'cpu7', []], ['s0c3t1', 'cpu15', []]]], [[['s1c0t0', 'cpu0', []], ['s1c0t1', 'cpu8', []]], [['s1c1t0', 'cpu2', []], ['s1c1t1', 'cpu10', []]], [['s1c2t0', 'cpu4', []], ['s1c2t1', 'cpu12', []]], [['s1c3t0', 'cpu6', []], ['s1c3t1', 'cpu14', []]]]]
	#pInfo = [[[['s0c0t0', 'cpu1', []], ['s0c0t1', 'cpu9', []]], [['s0c1t0', 'cpu3', []], ['s0c1t1', 'cpu11', []]], [['s0c2t0', 'cpu5', []], ['s0c2t1', 'cpu13', []]], [['s0c3t0', 'cpu7', []], ['s0c3t1', 'cpu15', []]]]]
	#vInfo = [(7, 4), (8, 4), (9, 2), (10, 1)]
	
	deviseAndApplyStrategy()
