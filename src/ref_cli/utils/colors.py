"""
Color utility module for CLI output colorization.
"""
from colorama import Fore, Back, Style
import functools

def colorize(color):
    """
    Decorator to colorize text output.
    
    Args:
        color: Colorama color code to use
        
    Returns:
        Decorated function that wraps text with color codes
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            text = func(*args, **kwargs)
            return f"{color}{text}{Style.RESET_ALL}"
        return wrapper
    return decorator

# Color utility functions
def success(text: str) -> str:
    """Format text as success message (bright green)"""
    return f"{Fore.LIGHTGREEN_EX}{text}{Style.RESET_ALL}"

def error(text: str) -> str:
    """Format text as error message (bright red)"""
    return f"{Fore.LIGHTRED_EX}{text}{Style.RESET_ALL}"

def warning(text: str) -> str:
    """Format text as warning message (bright yellow)"""
    return f"{Fore.LIGHTYELLOW_EX}{text}{Style.RESET_ALL}"

def info(text: str) -> str:
    """Format text as info message (bright cyan)"""
    return f"{Fore.LIGHTCYAN_EX}{text}{Style.RESET_ALL}"

def url(text: str) -> str:
    """Format text as URL (bright blue)"""
    return f"{Fore.LIGHTBLUE_EX}{text}{Style.RESET_ALL}"

def title(text: str) -> str:
    """Format text as title (bright magenta)"""
    return f"{Fore.LIGHTMAGENTA_EX}{text}{Style.RESET_ALL}"

def highlight(text: str) -> str:
    """Format text as highlighted (bright white)"""
    return f"{Fore.LIGHTWHITE_EX}{text}{Style.RESET_ALL}"

def dim(text: str) -> str:
    """Format text as dimmed (darker shade but still visible)"""
    return f"{Fore.LIGHTBLACK_EX}{text}{Style.RESET_ALL}" 