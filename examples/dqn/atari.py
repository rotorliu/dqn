from datetime import datetime
import random
import itertools
import os.path
from subprocess import Popen
from collections import deque

import numpy as np
import caffe
import matplotlib.pyplot as plt
import Image

import utils
from ntsc_palette import NTSCPalette
from create_action_sidebar import ActionSidebarImages


class Atari(object):
    MAX_HISTORY_LENGTH = 1000000

    def __init__(self):
        self.process = self.launch()
        self.game_over = False
        self.fin  = open('/s/ale_0.4.4/ale_0_4/ale_fifo_out', 'w+')
        self.fout = open('/s/ale_0.4.4/ale_0_4/ale_fifo_in',  'w+')
        self.i = 0
        self.palette = NTSCPalette()
        self.previous_experience = None
        self.previous_recorded = False
        self.record_rewarding = False
        # Handshake
        self.width, self.height = self.read_width_height()
        self.write('1,0,0,1\n')  # Ask to send (screen, RAM, n/a, episode)
        self.rewarding_experience_pairs = deque(maxlen=self.MAX_HISTORY_LENGTH)
        self.experience_pairs = deque(maxlen=self.MAX_HISTORY_LENGTH)
        self.action_images = ActionSidebarImages()

    def stop(self):
        self.fin.close()
        self.fout.close()
        self.process.kill()

    def read_width_height(self):
        str_in = self.read()
        width, height = str_in.split('-')
        print 'width:  ', width
        print 'height: ', height
        return int(width), int(height)

    def read(self):
        return self.fin.readline().strip()

    def write(self, s):
        self.fout.write(s)
        self.fout.flush()

    def show_image(self, im):
        # im = im[:, :, ::-1]
        Image.fromarray(im, 'RGB').save('atari.png')
        plt.imshow(im, interpolation='nearest')
        plt.show()

    def show_checkpoint_image(self, im):
        if self.i % 100 == 0 and os.path.isfile('show_screen'):
            self.show_image(im)

    def send_action(self, action):
        self.write("%d,%d\n" % (action.value, 18))  # 18 = Noop player b.

    def get_random_transitions(self, num):
        if len(self.experience_pairs) > num:
            i = random.randint(0, len(self.experience_pairs) - num)
            return list(itertools.islice(self.experience_pairs, i, i + num))
        else:
            return []

    def record_rewarding_experience(self, experience_pair, total_reward):
        if self.previous_experience and total_reward != 0 or self.game_over:
            # Record pairs of experiences where the second experience contains
            # a reward.
            self.rewarding_experience_pairs.append(experience_pair)

    def experience(self, n, action):
        total_reward = 0
        ret = []
        for _ in itertools.repeat(None, n):
            reward, experience = self.experience_frame(action)
            total_reward += reward
            ret.append(experience)
        if self.previous_experience:
            experience_pair = (self.previous_experience, ret)
            self.experience_pairs.append(experience_pair)
            if self.record_rewarding:
                self.record_rewarding_experience(experience_pair, total_reward)
        self.previous_experience = ret
        return ret

    def experience_frame(self, action):
        """ Load frame from game video.
        Returns: (image, action, game_over, reward)
        """
        # screen_hex = width x height x 2-Hex-NTSC-color
        screen_hex, episode, _ = self.read().split(':')
        image = self.get_image_from_screen_hex(screen_hex)
        image_action = self.add_action_sidebar(image, action)
        game_over, reward = self.get_game_over_and_reward(episode)
        experience = (image_action, action, game_over, reward)
        self.send_action(action)
        return reward, experience

    def get_reward_from_experience(self, experience):
        """Returns sum of rewards
        """
        total_reward = sum([e[3] for e in experience])
        if self.get_game_over_from_experience(experience):
            # Game over is -1
            print '\n\n\n\NEGATIVE REWARD\n\n\n\n'
            total_reward = -1

        # Since the scale of scores varies greatly from game to game,
        # we fixed all positive rewards to be 1 and all negative rewards to be  1
        # leaving 0 rewards unchanged.
        if total_reward > 0:
            total_reward = 1
        elif total_reward < 0:
            total_reward = -1

        return total_reward

    def get_game_over_from_experience(self, experience):
        return any([e[2] for e in experience])

    def get_state_from_experience(self, experience):
        return [e[0] for e in experience]

    def get_action_from_experience(self, experience):
        return experience[0][1]

    def get_game_over_and_reward(self, episode):
        # From ALE manual.pdf:
        # The episode string contains two comma-separated integers
        # indicating episode termination (1 for termination, 0 otherwise)
        # and the most recent reward. It is also colon-terminated.
        game_over, reward = episode.split(',')
        game_over = True if game_over == '1' else False
        reward = int(reward)
        self.game_over = game_over
        return game_over, reward

    def get_image_from_screen_hex(self, screen_hex):
        """ Returns w x h x gray_level """
        colors = []
        for color in color_chunks(screen_hex):
            colors.append(self.palette.colors[int(color, 16)])  # 16 For 2-hex
        # Reshape flat to h x w x RGB
        im = np.reshape(np.array(colors), (self.height, self.width, 3))
        im = utils.rgb2gray(im)
        # Resize to dimensions in DQN paper, TODO: pass dims as param.
        im = caffe.io.resize_image(im, (84, 80))
        self.show_checkpoint_image(im)
        self.i += 1
        if self.i % 10 == 0:
            print datetime.now(), 'ten frames'
        return im

    def launch(self):
        ale_location = "/s/ale_0.4.4/ale_0_4/"
        rom_location = "roms/"
        ale_bin_file = "ale"
        rom_file = 'space_invaders.bin'
        # Run A.L.E
        args = [
            ale_location + ale_bin_file,
            '-run_length_encoding', 'false',
            '-display_screen',      'true',
            '-game_controller',     'fifo_named',
            '-frame_skip',          '3',  # TODO: Change to 4 for other games per dqn paper.
            rom_location + rom_file
        ]
        return Popen(args, cwd='/s/ale_0.4.4/ale_0_4/', close_fds=True)

    def add_action_sidebar(self, image, action):
        action_image = self.action_images.images[action.value]
        action_image = np.array(action_image, dtype=np.float64)

        return np.concatenate((image, action_image), axis=1)


def color_length_chunks(l):
    """ Yield successive 2-hex, 2-hex chunks from l.
    """
    for i in xrange(0, len(l), 4):
        yield l[i: i + 2], l[i + 2: i + 4]


def color_chunks(l):
    """ Yield successive 2-hex, 2-hex chunks from l.
    """
    for i in xrange(0, len(l), 2):
        yield l[i: i + 2]
