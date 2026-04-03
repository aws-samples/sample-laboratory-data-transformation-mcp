# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Tests for the allotrope-mcp-server package."""

import importlib
import re


class TestInit:
    """Tests for the __init__.py module."""

    def test_version(self):
        """Test that __version__ is defined and follows semantic versioning."""
        import allotrope_mcp_server

        assert hasattr(allotrope_mcp_server, '__version__')
        assert isinstance(allotrope_mcp_server.__version__, str)

        version_pattern = r'^\d+\.\d+\.\d+$'
        assert re.match(version_pattern, allotrope_mcp_server.__version__), (
            f"Version '{allotrope_mcp_server.__version__}' does not follow semantic versioning"
        )

    def test_module_reload(self):
        """Test that the module can be reloaded."""
        import allotrope_mcp_server

        original_version = allotrope_mcp_server.__version__
        importlib.reload(allotrope_mcp_server)
        assert allotrope_mcp_server.__version__ == original_version
