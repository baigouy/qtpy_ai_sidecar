"""Expose meaningful leaf errors instead of opaque TaskGroup wrappers."""
def error_details(error):
    children = getattr(error, 'exceptions', None)
    if children:
        details = []
        for child in children:
            text = error_details(child)
            if text not in details:
                details.append(text)
        return '; '.join(details)
    cause = error.__cause__
    if cause is not None:
        return str(error) + ': ' + error_details(cause)
    return str(error) or type(error).__name__
