"""Compatibility import; implementation belongs to the product package."""
from .product.product_workspace import ProductWorkspace,WorkspaceConflict

__all__=['ProductWorkspace', 'WorkspaceConflict']
