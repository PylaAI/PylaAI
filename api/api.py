from io import BytesIO
import os

import requests
from PIL import Image


brawlers_url = "https://api.brawlapi.com/v1/brawlers"
brawlers_data = requests.get(brawlers_url).json()['list']

for brawler_obj in brawlers_data:
    icon_url = brawler_obj['imageUrl2']
    response = requests.get(icon_url)
    image = Image.open(BytesIO(response.content))
    brawler_name = str(brawler_obj['name']).lower()
    brawler_name = os.path.basename(brawler_name).replace('.', '').replace('/', '').replace('\\', '')
    image.save(f"./assets/brawler_icons2/{brawler_name}.png")
