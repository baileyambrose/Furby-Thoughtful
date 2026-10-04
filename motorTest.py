from gpiozero import Motor, Button
from time import sleep

# Motor(IN1, IN2, enable=EN)
motor = Motor(20, 21, enable=16)
button = Button(12, pull_up=True)

print("Motor test starting...")

print("Forward...")
motor.backward(.5)
sleep(0.2)
motor.forward()
button.wait_for_press()

print("Stop...")
# Manual brake: both inputs HIGH
motor.forward_device.on()
motor.backward_device.on()
sleep(1.5)

print("Backward...")
motor.backward(.5)
sleep(0.3)

button.wait_for_press()

print("Stop...")
motor.forward_device.on()
motor.backward_device.on()
sleep(1)
motor.stop()
