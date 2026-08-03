from setuptools import find_packages, setup

setup(
    name="zph",
    version="0.3.4",
    description="Command-line client for the Zephyr ALAMO simulation service",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    license="MIT",
    author="Solid Mechanics Research Group",
    url="https://zephyr.solids.group",
    project_urls={
        "Source": "https://github.com/solidsgroup/zephyr",
        "Issues": "https://github.com/solidsgroup/zephyr/issues",
    },
    package_dir={"": "src"},
    packages=find_packages("src"),
    python_requires=">=3.7",
    install_requires=[],
    extras_require={
        "dev": [
            "pytest>=7.4,<8; python_version < '3.8'",
            "pytest>=8.3,<9; python_version >= '3.8'",
            "ruff>=0.9,<1; python_version >= '3.9'",
        ]
    },
    entry_points={"console_scripts": ["zph=zephyr_cli.main:main"]},
    keywords=["alamo", "simulation", "provenance", "hpc"],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
