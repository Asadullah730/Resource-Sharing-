"""Kubernetes-agnostic resource sharing.

Share / use / certificate / matching never talk to Kubernetes or Docker.
Compute isolation goes through ComputePort. Kubernetes is one optional
adapter, selected only in bootstrap.
"""

__version__ = "0.1.0"
