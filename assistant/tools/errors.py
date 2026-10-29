class ToolError(Exception):
    """A problem Claude can fix by calling the tool differently; the message is sent back to Claude as is."""
