"""Kubernetes-agnostic resource sharing.

The application never talks to Kubernetes (or Docker) directly. All VM
lifecycle goes through ComputeBackend, selected at runtime.
"""

__version__ = "0.1.0"
