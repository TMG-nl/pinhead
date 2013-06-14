#!/usr/bin/python2.7
#import os
#import subprocess
import logging
import logging.handlers
import pinhead

class PinHeadRunHook(object):
	def pre(self, *args, **kwargs):
		pass

	def post(self, rv, *args, **kwargs):
		# set up logging
		log = logging.getLogger(__name__)
		log.setLevel(logging.DEBUG)
		handler = logging.handlers.SysLogHandler(address = '/dev/log')
		formatter = logging.Formatter('pinhead.%(funcName)s: %(message)s')
		handler.setFormatter(formatter)
		log.addHandler(handler)

		# do the pinhead run
		#curPath = os.path.dirname(__file__)
		log.info("Hook called. Doing the pinhead run...")
		
		try:
			#exitCode = subprocess.call(['/usr/bin/python2.7', curPath + '/pinhead.py'])
			exitCode = pinhead.deviseAndApplyStrategy()

			if exitCode == 0:
				log.info("Pinhead run exited successfully")
			else:
				log.error("Pinhead run exited with an error. Exit code: %s" % (str(exitCode)))
		except:
			log.error("Pinhead could not run")


if __name__ == "__main__":
	testMe = PinHeadRunHook()
	testMe.post(1)
