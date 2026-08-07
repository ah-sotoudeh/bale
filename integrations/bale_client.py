def get_channel_info(channel_link_or_id: str) -> dict:
    """Fetch channel info (title, bio, etc.) from Bale API.

    Returns a dict like {'title': '...', 'bio': '...'} or {} on error.
    """
    logger.info(f"Fetching channel info for {channel_link_or_id}")
    # Placeholder: actual endpoint/name depends on Bale's API
    url = f"{BALE_API_URL}/channels/get"
    payload = {'link': channel_link_or_id}
    try:
        r = requests.get(url, params=payload, headers=HEADERS, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logger.exception('Failed to get channel info')
        return {}
