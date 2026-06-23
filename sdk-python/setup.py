#!/usr/bin/env python3
"""Setup configuration for orchestrator-sdk."""

from setuptools import setup, find_packages

# Read the contents of README file
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="agentic-workflow-orchestrator",
    version="1.1.1",
    author="Manikandan Kasi",
    author_email="nxtgenai@gmail.com",
    description="Orchestrate multi-agent workflows with autonomous reasoning, parallelism, rate limiting, and LLM integration",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/kasimanikandan/agentic-workflow-orchestrator",
    packages=find_packages(where="."),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=[
        # No required dependencies. The SDK works standalone (Python engine)
        # or can spawn the external Go-based orchestrator engine.
    ],
    extras_require={
        "llm-anthropic": ["anthropic>=0.7.0"],
        "llm-openai": ["openai>=1.0.0"],
        "llm-gemini": ["google-generativeai>=0.3.0"],
        "llm-xai": ["openai>=1.0.0"],
        "llm-huggingface": ["transformers>=4.30.0", "torch>=2.0.0"],
        "llm-azure": ["openai>=1.0.0"],
        "llm": [
            "anthropic>=0.7.0",
            "openai>=1.0.0",
            "google-generativeai>=0.3.0",
            "transformers>=4.30.0",
            "torch>=2.0.0",
        ],
        "engine": [],
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "black>=23.0",
            "isort>=5.12",
            "mypy>=1.0",
        ],
    },
    project_urls={
        "Documentation": "https://github.com/kasimanikandan/agentic-workflow-orchestrator/blob/main/QUICKSTART.md",
        "Source": "https://github.com/kasimanikandan/agentic-workflow-orchestrator",
        "Tracker": "https://github.com/kasimanikandan/agentic-workflow-orchestrator/issues",
    },
)
