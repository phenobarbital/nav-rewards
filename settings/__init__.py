from navconfig import config, BASE_DIR

AUTHENTICATION_BACKENDS = (
    # 'navigator_auth.backends.TokenAuth',
    # 'navigator_auth.backends.TrocToken',
    # 'navigator_auth.backends.GoogleAuth',
    # 'navigator_auth.backends.OktaAuth',
    # 'navigator_auth.backends.ADFSAuth',
    # 'navigator_auth.backends.AzureAuth',
    # 'navigator_auth.backends.GithubAuth',
    # 'navigator_auth.backends.DjangoAuth',
    'navigator_auth.backends.BasicAuth',
    # 'navigator_auth.backends.NoAuth',
)
