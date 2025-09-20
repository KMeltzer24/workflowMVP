from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="workflowmvp",
    version="0.1.0",
    author="Kevin Meltzer",
    author_email="kevinmeltzer1@gmail.com",
    description="A Python project for workflow management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/KMeltzer24/workflowmvp",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=[
        "google-generativeai>=0.3.0",
        "requests>=2.28.0",
        "python-dotenv>=1.0.0",
        "opencv-python>=4.9.0.80",
        "flask>=2.3.0",
    ],
)
