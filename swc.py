import argparse
import json
import os
import re
import time
import urllib
from collections import namedtuple
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dateparser
import requests
from ics import Calendar, Event
from matplotlib import pyplot, ticker


_GET_ITEMS_BATCH_SIZE = 200
_LAST_DAY = '-12-31'
_NAME = 'name'
_PRERELEASE = 'prerelease'
_RELEASE_DATE = 'release_date'
_RELEASE_STRING = 'release_string'
_RELEASED = 'released'
_SEP = '-09-15'
_SHORT_DESCRIPTION = 'short_description'
_TOTAL = 'total'
_TYPE = 'type'
# The GetItems API is more reliable. It should be preferred in most cases.
_USE_GET_ITEMS_API = True
_UTC = timezone.utc
_YEAR_ONLY_REGEX = '^(\\d{4}) \\.$'

_BLOCK_LIST = ('tbd', 'tba', 'to be announced', 'when it\'s done', 'when it\'s ready', '即将推出', '即将宣布', 'coming soon')
_TO_REPLACE = (
    ('spring', 'mar'), ('summer', 'june'), ('fall', 'sep'), ('winter', 'dec'),
    ('q1', 'feb'), ('q2', 'may'), ('q3', 'aug'), ('q4', 'nov'),
    ('第一季度', 'feb'), ('第二季度', 'may'), ('第三季度', 'aug'), ('第四季度', 'nov'),
    ('年', '.'), ('月', '.'), ('日', '.'), ('号', '.')
)


def last_day_of_next_month(dt):
    """
    Returns the datetime of the last day of the next month.

    Args:
    dt: A datetime.datetime object.

    Returns:
    A datetime.datetime object.
    """

    year = dt.year
    next_next_month = dt.month + 2
    if next_next_month > 12:
        next_next_month -= 12
        year = dt.year + 1

    # Subtracting 1 day from the first day of the next next month, to get the last day of next month.
    return datetime(year, next_next_month, 1) - timedelta(days=1)


def get_wishlist_appids(steamid):
    url = f'https://api.steampowered.com/IWishlistService/GetWishlist/v1/?steamid={steamid}'

    response = requests.get(url, timeout=30)

    # In case of broken Steam API
    if response.status_code == 200:
        try:
            response_data = response.json()
        except requests.exceptions.JSONDecodeError:
            exit()

    wishlist_appids = []
    if 'response' in response_data and 'items' in response_data['response']:
        for item in response_data['response']['items']:
            if 'appid' in item:
                wishlist_appids.append(int(item['appid']))

    return sorted(wishlist_appids)


GameDetails = namedtuple('GameDetails', [_NAME, _TYPE, _RELEASE_STRING, _SHORT_DESCRIPTION, _PRERELEASE])


def get_game_details(appid):
    url = f'https://store.steampowered.com/api/appdetails?appids={appid}'
    try:
        response = requests.get(url, timeout=30)
    except Exception as e:
        print(f'Unexpected error: {e}')
        return GameDetails(
            name='',
            type='',
            release_string='',
            short_description='',
            prerelease=False
        )

    if response.status_code != 200:
        return GameDetails(
            name='',
            type='',
            release_string='',
            short_description='',
            prerelease=False
        )

    response_data = response.json()
    app_data_wrapper = response_data.get(str(appid), {})
    if not app_data_wrapper.get('success'):
        return GameDetails(
            name='',
            type='',
            release_string='',
            short_description='',
            prerelease=False
        )

    app_data = app_data_wrapper.get('data', {})
    release_date = app_data.get(_RELEASE_DATE, {})
    prerelease = release_date.get('coming_soon', False)
    return GameDetails(
        name=app_data.get(_NAME, ''),
        type=app_data.get(_TYPE, ''),
        release_string=release_date.get('date', ''),
        short_description=app_data.get(_SHORT_DESCRIPTION, ''),
        prerelease=prerelease
    )


def get_game_details_via_get_items_api(appids):
    request_json = {
        'ids': [{'appid': appid} for appid in appids],
        'context': {
            # TODO: maybe expose this to config
            'language': 'english',
            'country_code': 'US',
            'steam_realm': 1
        },
        'data_request': {
            'include_release': True,
            'include_basic_info': True
        }
    }

    encoded_json_string = urllib.parse.quote(json.dumps(request_json))

    url = f'https://api.steampowered.com/IStoreBrowseService/GetItems/v1?input_json={encoded_json_string}'
    try:
        response = requests.get(url, timeout=30)
    except Exception as e:
        print(f'Unexpected error: {e}')
        return {}

    if response.status_code != 200:
        return {}

    response_data = response.json()
    store_items = response_data.get('response', {}).get('store_items', [])
    game_details_dict = {}

    for item in store_items:
        appid = item.get('appid')
        if not appid:
            continue

        name = item.get(_NAME)
        type_ = item.get(_TYPE)
        release = item.get('release', {})
        basic_info = item.get('basic_info', {})

        # Extract relevant fields
        steam_release_date = release.get('steam_release_date', 0)
        short_description = basic_info.get(_SHORT_DESCRIPTION, '')
        prerelease_ = release.get('is_coming_soon', False)
        custom_release_date_message = release.get('custom_release_date_message', '')

        # Create a GameDetails tuple
        game_details = GameDetails(
            name=name,
            type=type_,
            release_string=(
                datetime.fromtimestamp(steam_release_date, tz=_UTC).strftime("%Y-%m-%d")
                if steam_release_date > 0
                else custom_release_date_message
            ),
            short_description=short_description,
            prerelease=prerelease_
        )

        # Add to dictionary
        game_details_dict[appid] = game_details

    return game_details_dict


# Arguments
parser = argparse.ArgumentParser()
parser.add_argument('-i', '--id', type=str, required=True)
parser.add_argument('-d', '--include-dlc', type=bool, default=False)
args = parser.parse_args()

if not args.id.isnumeric():
    print('Steam ID should be numeric.')
    exit()

now = datetime.now(_UTC)

# Initialize empty containers and counters
wishlist_data = {}
prerelease_count = 0
successful_deductions = []

wishlist_appids = get_wishlist_appids(args.id)

if _USE_GET_ITEMS_API:
    # Process the appids in batches, as the GetItems API will return error for request that is too large
    wishlist_appid_batches = [wishlist_appids[i:i + _GET_ITEMS_BATCH_SIZE] for i in range(0, len(wishlist_appids), _GET_ITEMS_BATCH_SIZE)]
    for batch in wishlist_appid_batches:
        wishlist_data.update(get_game_details_via_get_items_api(batch))
        time.sleep(3)
else:
    for appid in wishlist_appids:
        # Try 20 times, as there can be transient errors with this API
        for retry in range(20):
            game_details = get_game_details(appid)
            if game_details.name:
                break
            time.sleep(5)
        else:
            print(f'Bad appid:{appid}')
            continue
        wishlist_data.update({appid: game_details})
        time.sleep(0.5)

# Process the wishlist data
cal = Calendar(creator='SteamWishlistCalendar')
for key, value in wishlist_data.items():
    game_name = value.name
    description_suffix = ''

    if value.prerelease:
        prerelease_count += 1

    release_string = value.release_string.lower()
    if any(substring in release_string for substring in _BLOCK_LIST):
        # Release date not announced.
        continue

    # Heuristically maps vague words such as 'Q1', 'summer' to months.
    for old, new in _TO_REPLACE:
        release_string = release_string.replace(old, new)

    release_string = release_string.strip()
    year_only_match = re.match(_YEAR_ONLY_REGEX, release_string)
    if year_only_match:
        # Release string only contains information about the year.
        year = year_only_match.group(1)
        # If XXXX.09.15 has already passed, use the last day of that year.
        sep_release_date = datetime.strptime(f'{year}{_SEP}', '%Y-%m-%d').replace(tzinfo=_UTC)
        release_string = f'{year}{_SEP}' if sep_release_date > now else f'{year}{_LAST_DAY}'

    # Try to parse a machine-readable date from the release string.
    translated_date = dateparser.parse(release_string,
                                       settings={
                                           'PREFER_DAY_OF_MONTH': 'last',
                                           'PREFER_DATES_FROM': 'future'})
    if translated_date:
        release_date = translated_date
        while value.prerelease and release_date.date() < now.date():
            # A game is pre-release but the estimated release date has already passed. In this case, pick the earliest last-of-a-month date in the future.
            # Note the difference between this case and the case where only a year is provided, which has been addressed above.
            release_date = last_day_of_next_month(release_date)
        description_suffix = f'\n\n{value.short_description}\n\nDate string from steam: "{value.release_string}"'
    else:
        print(f'Failed deduction: {key}\t\t{game_name}\t\t{value.release_string}')
        continue

    if not release_date:
        continue

    successful_deductions.append(f'{game_name}\t\t{release_date.date()}')
    if value.type == 'dlc' and not args.include_dlc:
        continue

    event = Event(uid=str(key), summary=game_name,
                  description=f'https://store.steampowered.com/app/{key}{description_suffix}',
                  begin=release_date, last_modified=now, dtstamp=now,
                  categories=['game_release'])
    event.make_all_day()
    cal.events.append(event)


# File outputs
_OUTPUT_FOLDER = 'output'
_SUCCESS_FILE = 'successful.txt'
_ICS_FILE = 'wishlist.ics'
_HISTORY_FILE = 'history.json'
_HISTORY_CHART_FILE = 'wishlist_history_chart.png'
_HISTORY_STACK_PLOT_FILE = 'wishlist_history_stack_plot.png'

_COLOR = '#EBDBB2'
_LINE_COLOR = '#FB4934'
_LINE_COLOR_ALT = '#B8BB26'
_LEGEND_BACKGROUND = '#282828'
_GRID_COLOR = '#A89984'
_LABEL_COLOR = '#FABD2F'
_BACKGROUND_COLOR = '#32302F'
_DPI = 600

output_folder = Path('output')
output_folder.mkdir(exist_ok=True)

# Write successful deductions
success_file = output_folder.joinpath(_SUCCESS_FILE)
with success_file.open('w', encoding='utf-8') as f:
    f.write('\n'.join(successful_deductions))

# Write the calendar
ics_file = output_folder.joinpath(_ICS_FILE)
with ics_file.open('w', encoding='utf-8') as f:
    f.write(cal.serialize())

# Overwrite history
history_file = output_folder.joinpath(_HISTORY_FILE)
data = {}
if history_file.is_file():
    with history_file.open() as f:
        data = json.load(f)
data[datetime.today().strftime('%Y-%m-%d')] = {_PRERELEASE: prerelease_count, _TOTAL: len(wishlist_appids)}
with history_file.open('w') as f:
    json.dump(data, f)


def set_spine_visibility(ax):
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.spines['bottom'].set_color(_COLOR)
    ax.spines['left'].set_color(_COLOR)


def set_legend(ax, location):
    legend = ax.legend(loc=location, frameon=True, labelcolor=_LABEL_COLOR)
    legend.get_frame().set_facecolor(_LEGEND_BACKGROUND)
    legend.get_frame().set_edgecolor(_GRID_COLOR)


def annotate_run_time(pyplot):
    pyplot.annotate(f'Last run: {now:%Y-%m-%d %H:%M:%S} UTC', (0.5, 0), (0, -60),
                    xycoords='axes fraction', ha='center', textcoords='offset points',
                    color=_COLOR, fontsize=8)


# Redraw a line chart.
fig, ax = pyplot.subplots(facecolor=_BACKGROUND_COLOR)
x, y = zip(*sorted({k: v[_TOTAL] for k, v in data.items()}.items()))
prerelease_x, prerelease_y = zip(*sorted({k: v[_PRERELEASE] for k, v in data.items()}.items()))

ax.xaxis.set_major_locator(ticker.MultipleLocator(max(1, int(len(x) / 8))))
y_range = max(max(y), max(prerelease_y)) - min(min(y), min(prerelease_y))
ax.yaxis.set_major_locator(ticker.MultipleLocator(max(1, int(y_range / 10))))

ax.plot(x, y, marker='.', color=_LINE_COLOR, label=_TOTAL)
ax.plot(prerelease_x, prerelease_y, marker='.', color=_LINE_COLOR_ALT, label=_PRERELEASE)
ax.tick_params(color=_GRID_COLOR, labelcolor=_LABEL_COLOR)
ax.set_facecolor(_BACKGROUND_COLOR)
ax.set_ylabel('# of items on Wishlist')
ax.yaxis.label.set_color(_LABEL_COLOR)
ax.axes.grid(color=_GRID_COLOR, linestyle='dashed')

set_spine_visibility(ax)
set_legend(ax, 'center left')

pyplot.title('Wishlist History', color=_LABEL_COLOR)
annotate_run_time(pyplot)
pyplot.grid(color=_GRID_COLOR)
fig.autofmt_xdate()
pyplot.savefig(output_folder.joinpath(_HISTORY_CHART_FILE), dpi=_DPI)

# Redraw a stack plot.
fig, ax = pyplot.subplots(facecolor=_BACKGROUND_COLOR)
ax.xaxis.set_major_locator(ticker.MultipleLocator(max(1, int(len(x) / 8))))
ax.yaxis.set_major_locator(ticker.MultipleLocator(max(1, int(max(max(y), max(prerelease_y)) / 10))))

ax.stackplot(x,
             [[total_count - prerelease_count for total_count, prerelease_count in zip(y, prerelease_y)],
              prerelease_y],
             labels=[_RELEASED, _PRERELEASE], colors=['#8EC07C', '#D3869B'])
ax.tick_params(color=_COLOR, labelcolor=_LABEL_COLOR)
ax.set_facecolor(_BACKGROUND_COLOR)
ax.set_ylabel('# of items on Wishlist')
ax.yaxis.label.set_color(_LABEL_COLOR)

set_spine_visibility(ax)
set_legend(ax, 'upper left')

pyplot.title('Wishlist History - Stack Plot', color=_LABEL_COLOR)
annotate_run_time(pyplot)
fig.autofmt_xdate()
pyplot.savefig(output_folder.joinpath(_HISTORY_STACK_PLOT_FILE), dpi=_DPI)
