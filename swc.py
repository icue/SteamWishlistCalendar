import argparse
import dateparser
import json
import os
import re
import requests
import time
import warnings
from datetime import datetime
from datetime import timezone
from ics import Calendar, Event
from matplotlib import pyplot
from matplotlib import ticker

# Ignores dateparser warnings regarding pytz.
warnings.filterwarnings(
    'ignore',
    message='The localize method is no longer necessary, as this time zone supports the fold attribute',
)

_SEP = '-09-15'
_TOTAL = 'total'
_RELEASE_DATE = 'release_date'
_RELEASE_STRING = 'release_string'
_RELEASED = 'released'
_PRERELEASE = 'prerelease'
_YEAR_REGEX = '^\\d{4}$'

_BLOCK_LIST = ('tbd', 'tba', 'to be announced', 'when it\'s done', 'when it\'s ready', '即将推出', 'coming soon')
_TO_REMOVE = ('coming', 'wishlist now', '!', '--', 'wishlist and follow', 'play demo now',
              'add to wishlist', 'wishlist to be notified', 'wishlist', '愿望单', '添加', 'now',
              '(', ')', '（', '）', '↘', '↙', '↓', ':', '：')
_TO_REPLACE = (
    ('spring', 'mar'), ('summer', 'june'), ('fall', 'sep'), ('winter', 'dec'),
    ('q1', 'feb'), ('q2', 'may'), ('q3', 'aug'), ('q4', 'nov'),
    ('early 2', 'march 2'), ('late 2', 'sep 2'), ('年末', 'dec'), ('年底', 'dec'),
    ('年', '.'), ('月', '.'), ('日', '.'), ('号', '.')
)


parser = argparse.ArgumentParser()
parser.add_argument('-i', '--id', type=str, required=True)
parser.add_argument('-p', '--max-page', type=int, default=20)
parser.add_argument('-d', '--include-dlc', type=bool, default=False)
args = parser.parse_args()

if args.id.isnumeric():
    url = f'https://store.steampowered.com/wishlist/profiles/{args.id}/wishlistdata/'
else:
    url = f'https://store.steampowered.com/wishlist/id/{args.id}/wishlistdata/'
# l may also be 'english' or 'tchinese'. See https://partner.steamgames.com/doc/store/localization
params = {'l': 'schinese'}
count = 0
prerelease_count = 0
successful_deductions = []
failed_deductions = []
cal = Calendar(creator='SteamWishlistCalendar')
now = datetime.now(timezone.utc)

for index in range(0, args.max_page):
    params['p'] = index
    response = requests.get(url, params=params)
    if not response.json():
        # No more remaining items.
        break
    if 'success' in response.json().keys():
        # User profile is private.
        exit()

    for key, value in response.json().items():
        count += 1
        game_name = value['name']
        description_suffix = ''
        if value[_RELEASE_DATE]:
            release_date = datetime.fromtimestamp(float(value[_RELEASE_DATE]))
        if _PRERELEASE in value:
            prerelease_count += 1
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
                # If XXXX.09.15 has already passed, uses the last day of that year.
                sep_release_date = datetime.strptime(release_string + _SEP, '%Y-%m-%d').date()
                release_string += _SEP if sep_release_date > now.date() else '-12-31'

            # Tries to parse a machine-readable date from the release string.
            translated_date = dateparser.parse(release_string,
                                               settings={
                                                   'PREFER_DAY_OF_MONTH': 'last',
                                                   'PREFER_DATES_FROM': 'future'})
            if translated_date:
                release_date = translated_date
                description_suffix = f'\nEstimation based on "{value[_RELEASE_STRING]}"'
            else:
                failed_deductions.append(f'{game_name}\t\t{value[_RELEASE_STRING]}')
                continue

        if not release_date:
            continue
        successful_deductions.append(f'{game_name}\t\t{release_date.date()}')
        if value['type'] == 'DLC' and not args.include_dlc:
            continue
        event = Event(uid=key, name=game_name,
                      description='https://store.steampowered.com/app/' + key + description_suffix,
                      begin=release_date, last_modified=now,
                      categories=['game_release'])
        event.make_all_day()
        cal.events.add(event)
    time.sleep(3)


# File outputs.
_OUTPUT_FOLDER = 'output/'
_SUCCESS_FILE = 'successful.txt'
_FAILURE_FILE = 'failed_deductions.txt'
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

os.makedirs(_OUTPUT_FOLDER, exist_ok=True)

with open(_OUTPUT_FOLDER + _SUCCESS_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(successful_deductions))
with open(_OUTPUT_FOLDER + _FAILURE_FILE, 'w', encoding='utf-8') as f:
    f.write('\n'.join(failed_deductions))
with open(_OUTPUT_FOLDER + _ICS_FILE, 'w', encoding='utf-8') as f:
    f.write(cal.serialize())

# Overwrites history.
history_file_path = _OUTPUT_FOLDER + _HISTORY_FILE
data = {}
if os.path.isfile(history_file_path):
    with open(history_file_path) as f:
        data = json.load(f)
data[datetime.today().strftime('%Y-%m-%d')] = {_PRERELEASE: prerelease_count, _TOTAL: count}
with open(history_file_path, 'w') as f:
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


# Redraws a line chart.
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
pyplot.savefig(_OUTPUT_FOLDER + _HISTORY_CHART_FILE, dpi=_DPI)


# Redraws a stack plot.
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
pyplot.savefig(_OUTPUT_FOLDER + _HISTORY_STACK_PLOT_FILE, dpi=_DPI)
