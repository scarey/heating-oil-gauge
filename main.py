# MIT License (MIT)
# Copyright (c) 2023 Stephen Carey
# https://opensource.org/licenses/MIT

# Micropython code for sensing heating oil tank level.

from machine import SoftI2C, Pin
import gc
from inches_to_gallons import inches_to_gallons
from ssd1306 import SSD1306_I2C as SSD
from writer import CWriter
import JBB30
from hcsr04 import HCSR04
import uasyncio as asyncio
from mqtt_local import config
from mqtt_as import MQTTClient


STATUS_TOPIC = 'esp32/oil/status'
GALLONS_TOPIC = 'esp32/oil/gallons'
MAX_INCHES = 44
# how far the sensor is above the tank.  you need to estimate this after the install.
# the offset needs to be added to the final calculation
SENSOR_OFFSET = 1.78

i2c = SoftI2C(scl=Pin(16), sda=Pin(17))
print(i2c.scan())

sensor = HCSR04(trigger_pin=21, echo_pin=22)

gallons = 0
previous_gallons = 0

oled_width = 128
oled_height = 32
gc.collect()  # Precaution before instantiating framebuf
ssd = SSD(oled_width, oled_height, i2c)


def sub_cb(topic, msg, retained):
    message_string = msg.decode()
    print("Received `{}` from `{}` topic".format(message_string, topic.decode()))


async def wifi_han(state):
    print('Wifi is ', 'up' if state else 'down')
    await asyncio.sleep(1)


async def conn_han(client):
    await online()


async def online():
    await client.publish(STATUS_TOPIC, 'Online', retain=True, qos=0)


async def update_display(client):
    await client.connect()
    await asyncio.sleep(2)  # Give broker time
    await online()
    print("Published as online...")
    while True:
        CWriter.set_textpos(ssd, 0, 0)  # In case previous tests have altered it
        ssd.fill(0)
        wri = CWriter(ssd, JBB30, verbose=False)
        wri.printstring(str(gallons))
        ssd.show()
        await asyncio.sleep(1)


def get_gallons():
    # the reading does a non-async sleeps totalling 15 microseconds which shouldn't bother the asyncio events
    distance = sensor.distance_mm() / 25.4
    print('Current distance: {}in\n'.format(distance))
    # ignore readings that can't be right
    if 0 + SENSOR_OFFSET <= distance <= MAX_INCHES + SENSOR_OFFSET:
        inches_of_oil = round((MAX_INCHES - distance + SENSOR_OFFSET), 1)
        return inches_to_gallons[inches_of_oil]
    return 0


def is_reading_reasonable(new_reading):
    """ Check if reading is within 5% of the previous """
    diff = new_reading - previous_gallons
    return abs(diff) < previous_gallons / 20


async def read_distance():
    global gallons, previous_gallons
    while True:
        try:
            new_gallons = get_gallons()
            if new_gallons == 0 or not is_reading_reasonable(new_gallons):
                print('Reading {} was not within tolerance, trying once more.'.format(new_gallons))
                await asyncio.sleep(2)
                new_gallons = get_gallons()
            previous_gallons = gallons
            gallons = new_gallons
            await client.publish(GALLONS_TOPIC, str(gallons), retain=True, qos=0)
            await asyncio.sleep(10)
        except Exception as e:
            print("Problem reading distance: {}".format(e))
        finally:
            await asyncio.sleep(10)

config['subs_cb'] = sub_cb
config['connect_coro'] = conn_han
config['wifi_coro'] = wifi_han
config['will'] = [STATUS_TOPIC, 'Offline', True, 0]

MQTTClient.DEBUG = True  # Optional
client = MQTTClient(config)
try:
    loop = asyncio.get_event_loop()
    loop.create_task(update_display(client))
    loop.create_task(read_distance())
    loop.run_forever()
finally:
    client.close()
    asyncio.new_event_loop()

