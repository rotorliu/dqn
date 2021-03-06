import time
import sys
import utils
from atari import Atari
import atari_actions as actions
from episode_stats import EpisodeStats
from dqn_solver import DqnSolver
from constants import *

EXPERIENCE_WINDOW_SIZE = 4


def go(solver_filename, start_iter):
    check_for_test_vars()
    start_timestamp = int(time.time())
    log_file_name = get_episode_log_filename(start_timestamp)
    utils.setup_matplotlib()
    solver = utils.get_solver(solver_filename)
    net = solver.net
    frame_dir_name = get_frame_dir_name(start_timestamp)
    os.makedirs(frame_dir_name)
    episode_count = 0
    atari = Atari(frame_dir_name, episode_count, start_timestamp, show_game())
    action = actions.MOVE_RIGHT_AND_FIRE
    episode_stats = EpisodeStats()
    dqn = DqnSolver(atari, net, solver, start_timestamp, start_iter)
    while dqn.iter < xrange(int(1E7)):  # 10 million training steps

        time1 = time.time()
        experience = atari.experience(EXPERIENCE_WINDOW_SIZE, action)
        time2 = time.time()
        print '%s function took %0.3f ms' % \
              ('experience', (time2 - time1) * 1000.0)

        time1 = time.time()
        q, action = dqn.perceive(experience)
        time2 = time.time()
        print '%s function took %0.3f ms' %\
              ('perceive', (time2 - time1) * 1000.0)


        time1 = time.time()
        exploit = dqn.should_exploit()
        time2 = time.time()
        print '%s function took %0.3f ms' %\
              ('should-exploit', (time2 - time1) * 1000.0)

        if not exploit:
            action = actions.get_random_action()

        time1 = time.time()
        episode_stat = dqn.learn_from_experience_replay()
        time2 = time.time()
        print '%s function took %0.3f ms' %\
              ('learn', (time2 - time1) * 1000.0)

        time1 = time.time()
        dqn.record_episode_stats(episode_stats, experience, q, action, exploit,
                                 episode_stat)
        time2 = time.time()
        print '%s function took %0.3f ms' %\
              ('record', (time2 - time1) * 1000.0)


        if atari.game_over or 'TEST_AFTER_GAME' in os.environ:
            EpisodeStats.log_csv(episode_count, episode_stats, log_file_name)
            episode_count += 1
            episode_stats = EpisodeStats()
            atari.stop()
            if 'TEST_AFTER_GAME' in os.environ:
                return
            atari = Atari(frame_dir_name, episode_count, start_timestamp,
                          show_game())
        dqn.iter += 1
        print 'dqn iteration: ', dqn.iter

def show_game():
    if os.path.isfile(DQN_ROOT + '/show-game'):
        return True
    else:
        return False

def forced(self):
    """Allows manually triggering exploit"""
    if self.iter % 1 == 0:
        self._forced_exploit = os.path.isfile('exploit')
    return self._forced_exploit


def check_for_test_vars():
    if 'TEST_NEGATIVE_REWARD_DECAY' in os.environ:
        print 'YOU ARE TESTING NEGATIVE REWARD DECAY !!!!!!!!!!!!!!!'
        time.sleep(3)


def get_episode_dir():
    return '%s/data/%s' % (DQN_ROOT, EPISODE_DIR_NAME)


def get_episode_log_filename(start_timestamp):
    return '%s/episode_log_%d.csv' % (get_episode_dir(), start_timestamp)


def get_frame_dir_name(start_timestamp):
    return '%s/frames_%d'     % (get_episode_dir(), start_timestamp)

if __name__ == '__main__':
    _solver_filename = None
    _start_iter = 0
    if len(sys.argv) > 1:
        _solver_filename = sys.argv[1]
    if len(sys.argv) > 2:
        _start_iter = int(sys.argv[2])  # For resume.
    go(_solver_filename, _start_iter)


# def set_gradients(i, net, q_max, q_values, action_index, reward):
#     # NOTE: Q-learning alpha is achieved via neural net (caffe) learning rate.
#     #   (r + gamma * maxQ(s', a') - Q(s, a)) * Q(s, a)
#     #   (r + gamma * q_new - q_old) * q_old
#     # i.e.
#     # q_new = [2, 4, 6, 8]
#     # q_old = [1, 2, 1, 2]
#     # gamma = 0.5
#     # reward = reward[random_state_index] = 2
#     # gamma * q_new = [1, 2, 3, 4]
#     # r + gamma * q_new = [3, 4, 5, 6] # Do this first because it's new value in essence
#     # r + gamma * q_new - q_old = [3, 4, 5, 6] - [1, 2, 1, 2] = [2, 2, 4, 4]
#     # (r + gamma * q_new - q_old) * q_old = [2, 2, 4, 4] * [1, 2, 1, 2] = [2, 4, 4, 8] # Do separately for each neuron / action (not a dot product)
#     # DOES NOT MAKE SENSE THAT BIGGER Q_OLD GIVES BIGGER GRADIENT CRAIG
#     # TODO: Try setting other actions to opposite gradient.
#     q_gradients = [0.0] * len(q_values)
#     q_old = q_values[action_index]
#     q_gradients[action_index] = -(reward + GAMMA * q_max - q_old)  # TODO: Try * q_old to follow dqn paper even though this doesn't make sense as larger q_old should not give larger gradient.
#     print 'reward', reward
#     print 'q_max', q_max
#     set_gradients_on_caffe_net(net, q_gradients)
