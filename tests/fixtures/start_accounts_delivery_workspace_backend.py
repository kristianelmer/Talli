"""Owned Accounts fixture entry point; ordinary product composition stays closed."""
from start_rf1086_workspace_backend import main


def application_factory():
    from accounts_delivery_browser_runtime import build_application
    return build_application()


if __name__=='__main__':main(application_factory=application_factory)
