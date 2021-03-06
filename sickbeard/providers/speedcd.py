# coding=utf-8
#
# This file is part of SickGear.
#
# SickGear is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SickGear is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with SickGear.  If not, see <http://www.gnu.org/licenses/>.

import re
import time
from urllib import quote, unquote

from . import generic
from sickbeard import logger
from sickbeard.bs4_parser import BS4Parser
from sickbeard.helpers import tryInt
import sickbeard


class SpeedCDProvider(generic.TorrentProvider):

    def __init__(self):
        generic.TorrentProvider.__init__(self, 'SpeedCD', update_freq=7*60)

        self.url_base = 'https://speed.cd/'
        self.urls = {'config_provider_home_uri': self.url_base,
                     'login': self.url_base + 'rss.php',
                     'login_action': None,
                     'do_login': self.url_base,
                     'search': self.url_base + 'V3/API/API.php'}

        self.categories = {'Season': [41, 53], 'Episode': [2, 49, 50, 55], 'anime': [30]}
        self.categories['Cache'] = self.categories['Season'] + self.categories['Episode']

        self.url = self.urls['config_provider_home_uri']

        self.username, self.password, self.digest, self.freeleech, self.minseed, self.minleech = 6 * [None]

    def _authorised(self, **kwargs):
        result = False
        if self.digest:
            digest = [x[::-1] for x in self.digest[::-1].rpartition('=')]
            self.digest = digest[2] + digest[1] + quote(unquote(digest[0]))
            params = dict(
                logged_in=(lambda y='': all(
                    [self.session.cookies.get_dict(domain='.speed.cd') and
                     self.session.cookies.clear('.speed.cd') is None or True] +
                    ['RSS' in y, 'type="password"' not in y, self.has_all_cookies(['speedian'], 'inSpeed_')] +
                    [(self.session.cookies.get('inSpeed_' + c) or 'sg!no!pw') in self.digest for c in ['speedian']])),
                failed_msg=(lambda y=None: None), post_params={'login': False})
            result = super(SpeedCDProvider, self)._authorised(**params)

        if not result and not self.failure_count:
            if self.digest:
                self.get_url('%slogout.php' % self.url_base, skip_auth=True, post_data={'submit.x': 24, 'submit.y': 11})
            self.digest = ''
            params = dict(
                logged_in=(lambda y='': all(
                    [self.session.cookies.get_dict(domain='.speed.cd') and
                     self.session.cookies.clear('.speed.cd') is None or True] +
                    [bool(y), not re.search('(?i)type="password"', y)] +
                    [re.search('(?i)Logout', y) or not self.digest
                     or (self.session.cookies.get('inSpeed_speedian') or 'sg!no!pw') in self.digest])),
                failed_msg=(lambda y='': (
                    re.search(r'(?i)(username|password)((<[^>]+>)|\W)*' +
                              '(or|and|/|\s)((<[^>]+>)|\W)*(password|incorrect)', y) and
                    u'Invalid username or password for %s. Check settings' or
                    u'Failed to authenticate or parse a response from %s, abort provider')),
                post_params={'form_tmpl': True})
            self.urls['login_action'] = self.urls.get('do_login')
            session = super(SpeedCDProvider, self)._authorised(session=None, resp_sess=True, **params)
            self.urls['login_action'] = None
            if session:
                self.digest = 'inSpeed_speedian=%s' % session.cookies.get('inSpeed_speedian')
                sickbeard.save_config()
                result = True
                logger.log('Cookie details for %s updated.' % self.name, logger.DEBUG)
            elif not self.failure_count:
                logger.log('Invalid cookie details for %s and login failed. Check settings' % self.name, logger.ERROR)
        return result

    def _search_provider(self, search_params, **kwargs):

        results = []
        if not self._authorised():
            return results

        items = {'Cache': [], 'Season': [], 'Episode': [], 'Propers': []}

        rc = dict((k, re.compile('(?i)' + v)) for (k, v) in {'get': 'download', 'fl': '\[freeleech\]'}.items())

        for mode in search_params.keys():
            rc['cats'] = re.compile('(?i)cat=(?:%s)' % self._categories_string(mode, template='', delimiter='|'))
            for search_string in search_params[mode]:
                post_data = dict((x.split('=') for x in self._categories_string(mode).split('&')),
                                 search=search_string.replace('.', ' ').replace('^@^', '.'),
                                 jxt=2, jxw='b', freeleech=('on', None)[not self.freeleech])

                data_json = self.get_url(self.urls['search'], post_data=post_data, json=True)
                if self.should_skip():
                    return results

                cnt = len(items[mode])
                try:
                    html = data_json.get('Fs', [{}])[0].get('Cn', [{}])[0].get('d')
                    if not html or self._has_no_results(html):
                        raise generic.HaltParseException

                    with BS4Parser(html, features=['html5lib', 'permissive']) as soup:
                        torrent_table = soup.find('table', attrs={'cellspacing': 0})
                        torrent_rows = [] if not torrent_table else torrent_table.find_all('tr')

                        if 2 > len(torrent_rows):
                            raise generic.HaltParseException

                        head = None
                        for tr in torrent_rows[1:]:
                            cells = tr.find_all('td')
                            if 4 > len(cells):
                                continue
                            try:
                                head = head if None is not head else self._header_row(tr)
                                seeders, leechers, size = [tryInt(n, n) for n in [
                                    cells[head[x]].get_text().strip() for x in 'seed', 'leech', 'size']]
                                if None is tr.find('a', href=rc['cats']) \
                                        or self.freeleech and None is rc['fl'].search(cells[1].get_text()) \
                                        or self._peers_fail(mode, seeders, leechers):
                                    continue

                                info = tr.find('a', 'torrent')
                                title = (info.attrs.get('title') or info.get_text()).strip()
                                download_url = self._link(tr.find('a', href=rc['get'])['href'])
                            except (AttributeError, TypeError, ValueError):
                                continue

                            if title and download_url:
                                items[mode].append((title, download_url, seeders, self._bytesizer(size)))

                except (StandardError, Exception):
                    time.sleep(1.1)

                self._log_search(mode, len(items[mode]) - cnt,
                                 ('search string: ' + search_string, self.name)['Cache' == mode])

            results = self._sort_seeding(mode, results + items[mode])

        return results

    def _episode_strings(self, ep_obj, **kwargs):

        return super(SpeedCDProvider, self)._episode_strings(ep_obj, sep_date='^@^', **kwargs)

    @staticmethod
    def ui_string(key):

        return 'speedcd_digest' == key and \
               'use... \'inSpeed_speedian=yy\' - warning: SpeedCD cookies often expire, ' \
               'username/pw may update them automatically, else update manually from browser' or ''


provider = SpeedCDProvider()
