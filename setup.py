from setuptools import setup, find_packages

setup(
    name="transit_providers",
    version="0.2.5",
    packages=find_packages(),
    install_requires=[
        "mobility-db-api>=0.5.1",
        "gtfs-realtime-bindings>=2.0.0",
        "protobuf>=5.29.6,<7",
        "httpx>=0.27.2",
        "python-dotenv>=1.0.0",
    ],
    python_requires=">=3.9",
) 
