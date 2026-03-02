from .utils.access_control import get_active_charity

def charity_context(request):
    """
    Ensures current_charity is available in all templates.
    """
    if not request.user.is_authenticated:
        return {}
        
    return {
        'current_charity': get_active_charity(request)
    }
