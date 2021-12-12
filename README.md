# Steam Wishlist Calendar
![Wishlist History](output/wishlist_history_chart.png?raw=true "Wishlist History")
 
![Wishlist History Stack Plot](output/wishlist_history_stack_plot.png?raw=true "Wishlist History Stack Plot")
---
**Instructions** ([简体中文/Simplified Chinese version](https://github.com/icue/SteamWishlistCalendar/wiki/%E4%BD%BF%E7%94%A8%E8%AF%B4%E6%98%8E))
1. Make sure your Steam profile is public.
2. `pip install -r requirements.txt`
3. `python ./swc.py -i={steam ID}`
    
   Optional parameters:
   * `-d`: whether to include DLCs. Default is `False`.
   * `-p`: maximum number of pages to process. Default is `20`. By design of Steam API, each page contains 100 items, so this determines how many items on the wishlist get processed in total. If the wishlist contains more than 2000 items, you may want to raise this number, or the data will be cut off.
4. When finished, the script generates 6 files in [`/output`](output/) directory.
    * [`wishlist.ics`](output/wishlist.ics): an `.ICS` file, which can be imported into common calendar applications, such as Google Calendar and Outlook. Learn more about this format on [Wikipedia](https://en.wikipedia.org/wiki/ICalendar).
    * [`history.json`](output/history.json): stores the number of wishlisted items, as well as the number of pre-releases among them, of the day. Keeps growing.
    * [`successful.txt`](output/successful.txt): stores the items that either has an explicit release date or has a vague release date successfully converted into an exact date. Each line contains first the item name, then the release date.
    * [`failed_deductions.txt`](output/failed_deductions.txt): stores the items that do not have a meaningful enough release date, or have a release string that is too complicated to parse.
    * [`wishlist_history_chart.png`](output/wishlist_history_chart.png): a line chart that shows the trend of the wishlist. What gets displayed here also depends on data in [`history.json`](output/history.json).
    * [`wishlist_history_stack_plot.png`](output/wishlist_history_chart.png): a stack plot that shows the trend of the wishlist. What gets displayed here also depends on data in [`history.json`](output/history.json).
5. Refer to the [workflow yml file](.github/workflows/analyze-wishlist.yml) in this repo, to automatically run the script on schedule.
6. If you choose to publish the `.ICS` file, such as on GitHub, you may then have your calendar app subscribe to that file. Effectively what you get is a calendar that syncs with the release dates of the items on your wishlist.