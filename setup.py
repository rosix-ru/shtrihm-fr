from setuptools import setup, find_packages
import shtrihmfr

setup(
    name='shtrihm-fr',
    version=shtrihmfr.__version__,
    description='Driver for Shtrih-M cash (fiscal) registers.',
    long_description=open('README.rst').read(),
    author='Grigoriy Kramarenko',
    author_email='root@rosix.ru',
    url='https://github.com/rosix-ru/shtrihm-fr/',
    license='GNU General Public License v3 or later (GPLv3+)',
    platforms='any',
    zip_safe=False,
    packages=find_packages(),
    include_package_data = True,
    install_requires=['pyserial'],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Topic :: Office/Business :: Financial :: Accounting',
        'Topic :: Office/Business :: Financial :: Point-Of-Sale',
        'Topic :: System :: Hardware :: Hardware Drivers',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Natural Language :: Russian',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.4',
    ],
)
