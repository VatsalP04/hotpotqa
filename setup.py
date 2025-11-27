"""
Setup script for HotpotQA NLP Pipeline.

This provides setuptools support for the package, allowing it to be
installed with pip install -e . for development.
"""

from setuptools import setup, find_packages
from pathlib import Path

# Read README for long description
readme_path = Path(__file__).parent / "README.md"
long_description = readme_path.read_text(encoding="utf-8") if readme_path.exists() else ""

# Read requirements
requirements_path = Path(__file__).parent / "requirements.txt"
requirements = []
if requirements_path.exists():
    with open(requirements_path, 'r') as f:
        requirements = [
            line.strip()
            for line in f
            if line.strip() and not line.startswith('#')
        ]

setup(
    name="hotpotqa-pipeline",
    version="1.0.0",
    description="Complete NLP pipeline for HotpotQA multi-hop question answering dataset",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="HotpotQA Pipeline Team",
    author_email="",
    url="https://github.com/yourusername/hotpotqa",
    packages=find_packages(where="."),
    package_dir={"": "."},
    python_requires=">=3.10",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.3.0",
            "pytest-cov>=4.1.0",
            "black>=23.3.0",
            "flake8>=6.0.0",
        ],
        "spacy": [
            "spacy>=3.5.0",
        ],
        "viz": [
            "matplotlib>=3.7.0",
            "seaborn>=0.12.0",
            "wordcloud>=1.9.0",
        ],
        "notebooks": [
            "jupyter>=1.0.0",
            "ipykernel>=6.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "hotpotqa-preprocess=scripts.run_preprocessing:main",
            "hotpotqa-validate=scripts.validate_data:main",
            "hotpotqa-analyze=scripts.analyze_dataset:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Text Processing :: Linguistic",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
    keywords="nlp question-answering hotpotqa multi-hop reasoning dataset",
    project_urls={
        "Bug Reports": "https://github.com/yourusername/hotpotqa/issues",
        "Source": "https://github.com/yourusername/hotpotqa",
    },
)
