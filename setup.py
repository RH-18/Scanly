from setuptools import find_packages, setup

setup(
    name="Scanly",
    version="2.0.0",
    author="Adam McGready",
    author_email="amcgreadyfreelance@gmail.com",
    description="Windows-native media organiser that mirrors Real-Debrid mounts into Jellyfin libraries",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/amcgready/Scanly",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "python-dotenv>=0.20.0",
        "requests>=2.28.0",
    ],
    entry_points={
        "console_scripts": [
            "scanly=scanly.main:main",
        ],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: Microsoft :: Windows",
    ],
    python_requires=">=3.10",
)
