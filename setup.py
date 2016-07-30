#!/usr/bin/env python
# -*- coding: utf-8 -*-

import githubflow_release

from setuptools import setup

requirements = [
	'clingon',
	'GitPython',
	'requests',
	'semver'
]

version = '0.0.1'  # TODO use git tag ;)

setup(
    name='githubflow_release',
    version=version,
    description="github flow release",
    author="Antoine Desbordes",
    author_email='antoine.desbordes@gmail.com',
    url='https://github.com/CanalTP/githubflow_release',
    packages=[
        'githubflow_release',
    ],
    package_dir={'githubflow_release': 'githubflow_release'},
    include_package_data=True,
    install_requires=requirements,
    license="MIT",
    zip_safe=False,
    keywords='cli',
    classifiers=[
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
    ],
    entry_points={'console_scripts': [
        'githubflow_release = githubflow_release.release:release',
    ]},
)

