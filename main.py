'''
This script is executed at system startup and contains all the functions needed to: 
- connect to the WiFi access point
- interact with the Telegram Bot
- handle bot users commands
- get temperature and humidity measures using DHT 11 Sensor and send them to bot users when requested
- detect motions and send alerts 


AUTHOR: Cosimo Bromo
CONTACT: cosimo.bromo@gmail.com
'''

########## Import Needed Libraries ##########
import network
import socket
import time
from time import sleep
from machine import Pin, I2C, ADC
import machine
import os
import struct
import urequests as requests
from Dht11 import DHT11, InvalidChecksum
import json
import ujson

    
########## Parameters and Input Files ##########
MOTION_DETECTED = 1
# Initialize Measurements
last_measurement = {"t": None, "h": None}
# Initialize Alarm State
alarm_active = False

# CREDENTIALS
with open("credentials.json", "r") as f:
    credentials = json.load(f)

ssid = credentials["wifi"]["ssid"]
password = credentials["wifi"]["password"]

# LOGS
try:
    with open("logs.json", "r") as f: 
        logs = json.load(f)
except: 
    print("No Valid Logfile Found!")
    logs = dict() 
    logs["last_message_processed"] = 0      # Saves the ID of the last message processed

# TELEGRAM BOT 
bot_api = credentials["telegram_bot"]["api_key"]
chat_ids=credentials["telegram_bot"]["chat_id"]
sendURL = f'https://api.telegram.org/bot{bot_api}/sendMessage'
readURL = f'https://api.telegram.org/bot{bot_api}/getUpdates'


########## Connect to WiFi Access Point ##########
def connect(wlan, ssid, password):
    '''
    This function handles the connection to the WiFi network, given SSID and Password from credentials file.

    Args: 
    - ssid:         network ssid
    - password:     network password

    Returns: 
    - ip:           IP Address Connection

    '''
    wlan.connect(ssid, password)
    n_checks = 20
    current_check = 0
    while wlan.isconnected() == False and current_check<=n_checks:
        current_check += 1
        print(f"Waiting for connection..., check number {current_check}")
        sleep(1)
    if wlan.isconnected(): 
        ip = wlan.ifconfig()[0]
        print(f"Connected on {ip}")
    else: 
        ip = None 
        print("Not connected") 
    return ip


########## Get Current Time from Server ##########
def set_time():
    NTP_DELTA = 2208988800
    host = "pool.ntp.org"
    NTP_QUERY = bytearray(48)
    NTP_QUERY[0] = 0x1B
    addr = socket.getaddrinfo(host, 123)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(1)
        res = s.sendto(NTP_QUERY, addr)
        msg = s.recv(48)
    finally:
        s.close()
    val = struct.unpack("!I", msg[40:44])[0]
    t = val - NTP_DELTA    
    tm = time.gmtime(t)
    machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
    
########## Telegram Bot Functions ##########
def receive_telegram_messages(url):
    '''
    This function allows to check possible commands sent to the bot. 

    Args: 
    - url:          URL for getting updates from telegram server

    Returns: 
    - messages:     list of messages received in the last 48 hours (as indicated by Telegram bot documentation) 
    - message_ids:  list of message ids of messages received in the last 48 hours (as indicated by Telegram bot documentation)
    - sender_ids:   list of sender ids of messages received in the last 48 hourse (as indicated by Telegram bot documentation)
    '''
    response = requests.get(url)
    data = ujson.loads(response.text)
    response.close()
    messages = []
    message_ids = []
    sender_ids = []
    for update in data.get('result', []):
        message = update.get('message', {}).get('text', '')
        message_id = update.get('message', {}).get('message_id', '')
        sender_id = update.get('message', {}).get('from', {}).get('id', '')
        messages.append(message)
        message_ids.append(message_id)
        sender_ids.append(sender_id)
    return messages, message_ids, sender_ids
    

def send_message(chatId, message):
    '''
    This function allows to send messages to users identified by chatId.

    Args: 
    - chatId: chat ID of the bot user to send the message to
    - message: string message to send
    '''
    response = requests.post(sendURL + "?chat_id=" + str(chatId) + "&text=" + message)
    response.close()

########## INPUT/OUTPUT PERIPHERALS #########

# Sensors 
dht_sensor = DHT11(Pin(16, Pin.OUT, Pin.PULL_DOWN))
pir_sensor = machine.Pin(17, machine.Pin.IN, machine.Pin.PULL_DOWN)

# Leds
onboard_led = machine.Pin("LED", machine.Pin.OUT)
onboard_led.off()
active_alarm_led = machine.Pin(Pin(0), machine.Pin.OUT)     # On when alarm is active
inactive_alarm_led = machine.Pin(Pin(1), machine.Pin.OUT)   # On when alarm is not active
active_alarm_led.off()
inactive_alarm_led.on()


########## NETWORK ACTIVATION ##########
wlan = network.WLAN(network.STA_IF)
wlan.active(True)

ip = connect(wlan, ssid, password)
time.sleep(3)
for chat_id in chat_ids:
    # Send Activation message to all chat ids
    send_message(chat_id, "Hello, I'm active")


# Mail Script Loop
while True:
    # CHECK NETWORK CONNECTION
    if wlan.isconnected() == False:
        ip = connect(wlan, ssid, password)
    else:
        pass

    # CHECK MOTION DETECTION
    if pir_sensor.value() == MOTION_DETECTED: 
        onboard_led.on()
        if alarm_active:
            for chat_id in chat_ids:
                send_message(chat_id, "ALERT! Motion detected")
    else: 
        onboard_led.off()
    
    time.sleep(0.5)
    
    # HUMIDITY and TEMPERATURE MEASUREMENT - DHT11
    try: 
        dht_sensor.measure()
    except:
        print("Error in reading from DHT11 Sensor!") 

    t = dht_sensor.get_temperature()
    h = dht_sensor.get_humidity()
    last_measurement["t"] = t
    last_measurement["h"] = h


    # FILL LAST MEASUREMENT MESSAGE
    temp_msg = "T: "+str(last_measurement['t'])
    hum_msg = "H: "+str(last_measurement['h'])
    time.sleep(0.5)
    
    # RETRIEVE USER COMMANDS
    try: 
        messages, message_ids, sender_ids = receive_telegram_messages(readURL)
        
        for idx, message in enumerate(messages):
            print(f"Received message: {message}, id: {message_ids[idx]}, sender: {sender_ids[idx]}")
            if message_ids[idx] > logs["last_message_processed"]:
                if message=="/alarmon": 
                    alarm_active = True
                    inactive_alarm_led.off()
                    active_alarm_led.on()
                    for chat_id in chat_ids: 
                        send_message(chat_id, "Alarm is ACTIVE")
                elif message=="/alarmoff": 
                    alarm_active = False
                    active_alarm_led.off()
                    inactive_alarm_led.on()
                    for chat_id in chat_ids: 
                        send_message(chat_id, "Alarm is INACTIVE")
                elif message=="/temp":
                    send_message(sender_ids[idx], temp_msg)
                elif message=="/humidity":
                    send_message(sender_ids[idx], hum_msg)

                logs["last_message_processed"] = message_ids[idx]

                # Writing to logs.json 
                with open("logs.json", "w") as logsfile:
                    logsfile.write(json.dumps(logs))
    except: 
        print("Error in getting commands")

    # SET CURRENT TIME FROM TIME SERVER
    try:
        set_time()
        current_local_time = time.localtime()
    except:
        print("No Time Got!")

    time.sleep(2)