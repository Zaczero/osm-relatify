def postprocessor(path, key, value):
    if key in ('@id', '@ref', '@changeset', '@uid'):
        return key, int(value)

    if key in ('@version',):
        try:
            return key, int(value)
        except ValueError:
            return key, float(value)

    return key, value
