import argparse
import dateparser
import json
import os
import re
import requests
import time
import warnings
from datetime import datetime
from ics import Calendar, Event
from matplotlib import pyplot

# Ignores dateparser warnings regarding pytz
warnings.filterwarnings(
    "ignore",
    message="The localize method is no longer necessary, as this time zone supports the fold attribute",
)

_CREATER = 'SteamWishlistCalendar'
_NAME = 'name'
_TYPE = 'type'
_DLC = 'DLC'
_SEP = ' sep'
_CATEGORY = 'game_release'
_RELEASE_DATE = 'release_date'
_RELEASE_STRING = 'release_string'
_PRERELEASE = 'prerelease'
_EVENT_SUFFIX = ' 发售'
_YEAR_REGEX = '^\\d{4}$'
_GAME_URL_PREFIX = 'https://store.steampowered.com/app/'

_BLOCK_LIST = ('tbd', 'tba', 'to be announced', 'when it\'s done', 'when it\'s ready', '即将推出', 'coming soon')
_TO_REMOVE = ('coming', 'wishlist now', '!', '--', 'wishlist and follow', 'play demo now',
              'add to wishlist', 'wishlist to be notified', 'wishlist', '愿望单', '添加'
              '(', ')', '（', '）', '↘', '↙', '↓', ':', '：')
_TO_REPLACE = (
    ('spring', 'mar'), ('summer', 'june'), ('fall', 'sep'), ('winter', 'dec'),
    ('q1', 'feb'), ('q2', 'may'), ('q3', 'aug'), ('q4', 'nov'),
    ('early 2', 'march 2'),
    (' 年 ', '年'), (' 月 ', '月'),
    (' 年', '年'), (' 月', '月'), (' 日', '日'),
    ('年 ', '年'), ('月 ', '月'),
    ('年末', 'dec')
)

_SUCCESS_FILE = '/successful.txt'
_FAILURE_FILE = '/failed_deductions.txt'
_ICS_FILE = '/wishlist.ics'
_HISTORY_FILE = '/history.json'
_HISTORY_CHART_FILE = '/wishlist_history_chart.png'


parser = argparse.ArgumentParser()
parser.add_argument('-i', '--id', type=str, required=True)
parser.add_argument('-p', '--max-page', type=int, default=15)
parser.add_argument('-d', '--include-dlc', type=bool, default=False)
args = parser.parse_args()

if(args.id.isnumeric()):
    url = f'https://store.steampowered.com/wishlist/profiles/{args.id}/wishlistdata/'
else:
    url = f'https://store.steampowered.com/wishlist/id/{args.id}/wishlistdata/'
# l may also be 'english' or 'tchinese'. See https://partner.steamgames.com/doc/store/localization
params = {'l': 'schinese'}
count = 0
successful_deductions = []
failed_deductions = []
cal = Calendar(creator=_CREATER)
now = datetime.now()

for index in range(0, args.max_page):
    params['p'] = index
    response = requests.get(url, params=params)
    if not response.json():
        # No more remaining items.
        break

    for key, value in response.json().items():
        count += 1
        game_name = value[_NAME]
        if value[_RELEASE_DATE]:
            release_date = datetime.fromtimestamp(float(value[_RELEASE_DATE]))
        if _PRERELEASE in value:
            # Games that are not release yet will have a 'free-form' release string.
            release_string = value[_RELEASE_STRING].lower()
            if any(substring in release_string for substring in _BLOCK_LIST):
                # Release date not announced.
                continue
            # Removes noises.
            for w in _TO_REMOVE:
                release_string = release_string.replace(w, '')
            # Heuristically maps vague words such as 'Q1', 'summer' to months.
            for pair in _TO_REPLACE:
                release_string = release_string.replace(pair[0], pair[1])
            release_string = release_string.lstrip().rstrip()
            if re.match(_YEAR_REGEX, release_string):
                # Release string only contains a year.
                release_string += _SEP

            # Tries to parse a machine-readable date from the release string.
            translated_date = dateparser.parse(release_string,
                                               settings={
                                                   'PREFER_DAY_OF_MONTH': 'last',
                                                   'PREFER_DATES_FROM': 'future'})
            if translated_date:
                # print(value['release_string'] + '   translating to   ' + str(translated_date.date()))
                release_date = translated_date
            else:
                failed_deductions.append(f'{game_name}\t\t{value[_RELEASE_STRING]}')
                continue

        if not release_date:
            continue
        successful_deductions.append(f'{game_name}\t\t{release_date.date()}')
        if value[_TYPE] == _DLC and not args.include_dlc:
            continue
        event = Event(uid=key, name=game_name + _EVENT_SUFFIX,
                      description=_GAME_URL_PREFIX + key,
                      begin=release_date, last_modified=now,
                      categories=[_CATEGORY])
        event.make_all_day()
        cal.events.add(event)
    time.sleep(3)


os.makedirs(args.id, exist_ok=True)

with open(args.id + _SUCCESS_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(successful_deductions))

with open(args.id + _FAILURE_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(failed_deductions))

with open(args.id + _ICS_FILE, 'w', encoding='utf-8') as f:
    f.write(str(cal))

# Overwrites history.
history_file_path = args.id + _HISTORY_FILE
data = {}
if os.path.isfile(history_file_path):
    with open(history_file_path) as f:
        data = json.load(f)

data[datetime.today().strftime('%Y-%m-%d')] = count
with open(history_file_path, 'w') as f:
    json.dump(data, f)

# Redraws a line chart.
x, y = zip(*sorted(data.items()))
pyplot.plot(x, y, marker='.')
pyplot.xlabel('Date')
pyplot.ylabel('# of items on Wishlist')
pyplot.title('Wishlist History')
pyplot.savefig(args.id + _HISTORY_CHART_FILE)
