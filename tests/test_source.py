#
# Copyright (C) 2015 Michał Kępień <github@kempniu.pl>
#
# This file is part of evmapy.
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA

"""
Unit tests for the EventSource class
"""

import unittest
import unittest.mock

import evdev

import evmapy.source
import evmapy.util

import tests.util


@unittest.mock.patch('evmapy.config.load')
@unittest.mock.patch('logging.getLogger')
@unittest.mock.patch('socket.socket')
@unittest.mock.patch('evdev.InputDevice')
def mock_eventsource(*args):
    """
    Generate an EventSource with mocked attributes
    """
    (fake_inputdevice, fake_socket, fake_logger, fake_config_load) = args
    fake_eventmap = {
        100: {
            'alias':    'Foo',
            'code':     100,
            'min': {
                'id':       1,
                'value':    0,
                'type':     'key',
                'trigger':  'normal',
                'target':   'KEY_LEFT',
                'state':    'up',
            },
            'max': {
                'id':       2,
                'value':    255,
                'type':     'key',
                'trigger':  'normal',
                'target':   'KEY_RIGHT',
                'state':    'up',
            },
        },
        200: {
            'alias':    'Bar',
            'code':     200,
            'press': {
                'id':       3,
                'type':     'key',
                'trigger':  'normal',
                'target':   'KEY_ENTER',
            },
        },
        'grab': False,
    }
    device_attrs = {
        'name': 'Foo Bar',
        'fn':   '/dev/input/event0',
        'fd':   tests.util.DEVICE_FD,
    }
    tests.util.set_attrs_from_dict(fake_inputdevice.return_value, device_attrs)
    fake_socket.return_value.fileno.return_value = tests.util.CONFIG_FD
    fake_config_load.return_value = fake_eventmap
    device = fake_inputdevice()
    return {
        'device':   device,
        'logger':   fake_logger.return_value,
        'socket':   fake_socket.return_value,
        'source':   evmapy.source.EventSource(device, '/foo.json'),
    }


class TestSource(unittest.TestCase):

    """
    Test EventSource behavior
    """

    def setUp(self):
        """
        Create an EventSource to use with all tests
        """
        self.device = None
        self.logger = None
        self.socket = None
        self.source = None
        tests.util.set_attrs_from_dict(self, mock_eventsource())

    def test_source_events(self):
        """
        Check if EventSource properly translates all events
        """
        event_list = [
            (evdev.ecodes.ecodes['EV_KEY'], 300, evdev.KeyEvent.key_down),
            (evdev.ecodes.ecodes['EV_KEY'], 200, evdev.KeyEvent.key_down),
            (evdev.ecodes.ecodes['EV_KEY'], 200, evdev.KeyEvent.key_up),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 0),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 64),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 128),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 192),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 256),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 192),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 128),
            (evdev.ecodes.ecodes['EV_ABS'], 100, 64),
        ]
        expected_list = [
            ('KEY_ENTER', 'down'),
            ('KEY_ENTER', 'up'),
            ('KEY_LEFT', 'down'),
            ('KEY_LEFT', 'up'),
            ('KEY_RIGHT', 'down'),
            ('KEY_RIGHT', 'up'),
        ]
        fake_events = []
        for (ecode, etype, evalue) in event_list:
            fake_event = evdev.events.InputEvent(0, 0, ecode, etype, evalue)
            fake_events.append(fake_event)
        self.device.read.return_value = fake_events
        actions = self.source.process(tests.util.DEVICE_FD)
        for (action, direction) in actions:
            expected = expected_list.pop(0)
            self.assertTupleEqual((action['target'], direction), expected)
        self.assertEqual(expected_list, [])

    @unittest.mock.patch('evmapy.config.load')
    def test_source_config_load_file(self, fake_config_load):
        """
        Check if EventSource tries to load the proper configuration file
        when requested to
        """
        info = evmapy.util.get_app_info()
        config_path = info['config_dir'] + '/bar.json'
        self.socket.recv.return_value = b'bar.json\n'
        self.source.process(tests.util.CONFIG_FD)
        fake_config_load.assert_called_once_with(config_path)

    @unittest.mock.patch('evmapy.config.load')
    def test_source_config_load_invalid(self, fake_config_load):
        """
        Check how EventSource behaves when asked to load a non-existent
        configuration file
        """
        self.socket.recv.return_value = b'bar.json\n'
        fake_config_load.side_effect = FileNotFoundError()
        self.source.process(tests.util.CONFIG_FD)
        self.assertEqual(self.logger.error.call_count, 1)

    @unittest.mock.patch('evmapy.config.load')
    def test_source_config_load_default(self, fake_config_load):
        """
        Check how EventSource behaves when asked to reload the default
        configuration file
        """
        self.socket.recv.return_value = b'\n'
        self.source.process(tests.util.CONFIG_FD)
        config_path = evmapy.util.get_device_config_path(self.device)
        fake_config_load.assert_called_once_with(config_path)

    @unittest.mock.patch('evmapy.config.load')
    def test_source_config_load_grab(self, fake_config_load):
        """
        Check if EventSource properly grabs its underlying device when
        requested to
        """
        fake_config_load.side_effect = [
            {'grab': False},
            {'grab': True},
        ]
        self.source.process(tests.util.CONFIG_FD)
        self.source.process(tests.util.CONFIG_FD)
        self.assertEqual(self.device.grab.call_count, 1)

    @unittest.mock.patch('evmapy.config.load')
    def test_source_config_load_ungrab(self, fake_config_load):
        """
        Check if EventSource properly ungrabs its underlying device when
        requested to
        """
        fake_config_load.side_effect = [
            {'grab': True},
            {'grab': False},
        ]
        self.source.process(tests.util.CONFIG_FD)
        self.source.process(tests.util.CONFIG_FD)
        self.assertEqual(self.device.ungrab.call_count, 1)

    @unittest.mock.patch('os.remove')
    def test_source_cleanup(self, fake_remove):
        """
        Check if EventSource properly cleans up after itself
        """
        self.source.cleanup()
        self.socket.close.assert_called_once_with()
        self.assertEqual(fake_remove.call_count, 1)