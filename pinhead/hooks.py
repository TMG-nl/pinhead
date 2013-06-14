#!/usr/bin/python2.7
import subprocess
import logging
import logging.handlers

class PinHeadRunHook(object):
	def pre(self, *args, **kwargs):
		pass

	def post(self, rv, *args, **kwargs):
		# set up logging
		log = logging.getLogger(__name__)
		log.setLevel(logging.DEBUG)
		handler = logging.handlers.SysLogHandler(address = '/dev/log')
		formatter = logging.Formatter('%(module)s.%(funcName)s: %(message)s')
		handler.setFormatter(formatter)
		log.addHandler(handler)
		
		# do the pinhead run
		log.info("Hook called. Doing the pinhead run...")
		
		try:
			#exitCode = subprocess.call(['/usr/bin/python2.7', '/usr/lib64/python2.7/site-packages/pinhead/pinhead.py'])
			exitCode = 0
			if exitCode == 0:
				log.info("Pinhead run exited successfully")
			else:
				log.error("Pinhead run exited with an error. Exit code: %s" % (str(exitCode)))
		except:
			log.error("Pinhead could not run. Subprocess call failed")

if __name__ == "__main__":
	testMe = PinHeadRunHook()
	testMe.post(1)
