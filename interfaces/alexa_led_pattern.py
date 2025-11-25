#!/usr/bin/env python

# Copyright (C) 2017 Seeed Technology Limited
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time


class AlexaLedPattern(object):
    def __init__(self, show=None, number=12):
        self.pixels_number = number
        self.pixels = [0] * 4 * number

        if not show or not callable(show):

            def dummy(data):
                pass

            show = dummy

        self.show = show
        self.stop = False

    def wakeup(self, direction=0):
        position = (
            int((direction + 15) / (360 / self.pixels_number)) % self.pixels_number
        )

        pixels = [0, 0, 0, 24] * self.pixels_number
        pixels[position * 4 + 2] = 48

        self.show(pixels)

    def listen(self):
        pixels = [0, 0, 0, 0] * self.pixels_number

        # Create a spinning pattern: 3 pixels RED (intuitive for recording), rest off
        for i in range(3):
            pixels[i * 4 + 1] = 24

        while not self.stop:
            self.show(pixels)
            time.sleep(0.05)
            pixels = pixels[-4:] + pixels[:-4]

    def think(self):
        # Rotate Blue pixels (Processing)
        # Pattern: [?, Red=0, Green=0, Blue=24]
        pixels = [0, 0, 0, 24, 0, 0, 0, 12] * self.pixels_number

        while not self.stop:
            self.show(pixels)
            time.sleep(0.1)
            pixels = pixels[-4:] + pixels[:-4]

    def speak(self):
        # Breathing Green (Speaking/Playback)
        step = 1
        brightness = 0
        while not self.stop:
            # +2 is Green
            pixels = [0, 0, brightness, 0] * self.pixels_number
            self.show(pixels)
            time.sleep(0.01)

            if brightness <= 0:
                step = 1
                time.sleep(0.05)
            elif brightness >= 24:
                step = -1
                time.sleep(0.05)

            brightness += step

    def off(self):
        self.show([0] * 4 * 12)
