#!/usr/bin/python2.7
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
                log.info("Hook called. Doing the pinhead run...")

                try:
                        exitCode = pinhead.deviseAndApplyStrategy()
                        if exitCode == 0:
                                log.info("Pinhead run exited successfully")

                except SystemExit as e:
                        log.error("Pinhead run exited with error %s" % (e.code))

                except Exception:
                        log.error("Pinhead could not run. Unhandled exception")


if __name__ == "__main__":
        testMe = PinHeadRunHook()
        testMe.post(1)
