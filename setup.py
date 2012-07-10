#!/usr/bin/env python

from setuptools import setup

setup(
    name="python-photobucket",
    version="0.2",
    description="A python wrapper for the Photobucket API",
    author="Paulo Alvarado",
    author_email="commonzenpython@gmail.com",
    url="http://github.com/czpython/python-photobucket",
    packages=['photobucket'],
    install_requires=[
        'requests',
        'oauth2',
    ],
)