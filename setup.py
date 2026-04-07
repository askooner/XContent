from setuptools import setup, find_packages

setup(
    name="xcontent",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "google-api-python-client>=2.100.0",
        "youtube-transcript-api>=0.6.1",
        "anthropic>=0.40.0",
        "click>=8.1.0",
        "rich>=13.0.0",
        "python-dotenv>=1.0.0",
        "pyyaml>=6.0",
        "requests>=2.28.0",
    ],
    entry_points={
        "console_scripts": [
            "xcontent=xcontent.cli:main",
        ],
    },
)
