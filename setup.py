#!/usr/bin/python2.7

from setuptools import setup, find_packages

setup(name='pinhead',
	version='0.1.2',
	description='A tool for auto-pinning kvm vcpus to physical threads on the local machine (+ Nova hooks)',
	author='Giorgio Franceschi',
	author_email='g.franceschi@tmg.nl',
	packages=find_packages(),
	entry_points={'nova.hooks': {'pinheadrun=pinhead.hooks:PinHeadRunHook'}}
)
