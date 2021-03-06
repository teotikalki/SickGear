import ast
import base64
import re
import sickbeard
from helpers import tryInt


def read_config_string(data):

    return data and dict((tryInt(x[0]), x[1]) for x in ast.literal_eval(data)) or {}


def build_config(**kwargs):
    """
    kwargs is filtered for settings that enable updates to Trakt

    :param kwargs: kwargs to be filtered for settings that enable updates to Trakt
    :return: dict of parsed config kwargs where k is Trakt account id, v is a parent location
    """

    config = {}

    root_dirs = []
    if sickbeard.ROOT_DIRS:
        root_pieces = sickbeard.ROOT_DIRS.split('|')
        root_dirs = root_pieces[1:]

    for item in [re.findall('update-trakt-(\d+)-(.*)', k) for k, v in kwargs.items() if k.startswith('update-trakt-')]:
        for account_id, location in item:
            account_id = tryInt(account_id, None)
            if None is account_id:
                continue
            for cur_dir in root_dirs:
                account_id = tryInt(account_id, None)
                if account_id and base64.urlsafe_b64encode(cur_dir) == location:
                    if isinstance(config.get(account_id), list):
                        config[account_id] += [cur_dir]
                    else:
                        config[account_id] = [cur_dir]

    return config


def build_config_string(config):
    """
    :param config: dicts of Trakt account id, parent location
    :return: string csv of parsed config kwargs for config file
    """
    return unicode(config.items())


def trakt_collection_remove_account(account_id):
    if account_id in sickbeard.TRAKT_UPDATE_COLLECTION:
        sickbeard.TRAKT_UPDATE_COLLECTION.pop(account_id)
        sickbeard.save_config()
        return True
    return False
