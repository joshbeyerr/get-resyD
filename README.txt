Need an ENV file for adding RESY API Key which I am not going to publicly post here, and your own discord webhook

This is a web app that allows you to monitor any restauraunt on Resy.com for reservation availbility

Reason for this?
Many restauraunts that were on my go to list, were filling up instantly when releasing reservations, or I procrastinated and went to book last minute
This web app allows you to monitor for one off cancellations to snag, or when the restauraunt adds a full new haul of reservations

Instructions 
Simply input the Resy URL
    - e.g: https://resy.com/cities/toronto-on/venues/taverne-bernhardts
Select a start and end date for your reservations, times, party size and add to monitor
 - Again, must input RESY API Key, and your own discord webhook

As long as you keep the tab open, it will run the background. Each monitored item is an indepdant thread, so they can run concurrently with no problems
Only possible risk right now is if you add too many monitors and get your IP banned for too many requests on Resy.com
Current refresh time for the monitor is every 2 minutes

As stated above, you must input a discord webhook URL, and a successful notification will ping to this when the monitor finds something.

![Alt text](images/screenShot1.jpg)
![Alt text](images/screenShot2.jpg)
![Alt text](images/screenShot3.jpg)

Discord Webhook Example
![Alt text](images/ScreenShotDiscord.jpg)