from collections import OrderedDict
import numpy as np
from gym.spaces import  Dict , Box


from metaworld.envs.env_util import get_stat_in_paths, \
    create_stats_ordered_dict, get_asset_full_path
from metaworld.core.multitask_env import MultitaskEnv
from metaworld.envs.mujoco.sawyer_xyz.base import SawyerXYZEnv

from pyquaternion import Quaternion
from metaworld.envs.mujoco.utils.rotation import euler2quat
from metaworld.envs.mujoco.sawyer_xyz.base import OBS_TYPE


class SawyerDoorLockEnv(SawyerXYZEnv):
    def __init__(
            self,
            random_init=False,
            obs_type='plain',
            goal_low=None,
            goal_high=None,
            rotMode='fixed',
            **kwargs
    ):
        self.quick_init(locals())
        hand_low=(-0.5, 0.40, -0.15)
        hand_high=(0.5, 1, 0.5)
        obj_low=(-0.1, 0.8, 0.1)
        obj_high=(0.1, 0.85, 0.1)
        SawyerXYZEnv.__init__(
            self,
            frame_skip=5,
            action_scale=1./100,
            hand_low=hand_low,
            hand_high=hand_high,
            model_name=self.model_name,
            **kwargs
        )

        self.init_config = {
            'obj_init_pos': np.array([0, 0.85, 0.1]),
            'hand_init_pos': np.array([0, 0.6, 0.2], dtype=np.float32),
        }
        self.goal = np.array([0, 0.85, 0.1])
        self.obj_init_pos = self.init_config['obj_init_pos']
        self.hand_init_pos = self.init_config['hand_init_pos']

        assert obs_type in OBS_TYPE
        self.obs_type = obs_type

        if goal_low is None:
            goal_low = self.hand_low
        
        if goal_high is None:
            goal_high = self.hand_high

        self.random_init = random_init
        self.max_path_length = 150
        self.rotMode = rotMode
        if rotMode == 'fixed':
            self.action_space = Box(
                np.array([-1, -1, -1, -1]),
                np.array([1, 1, 1, 1]),
            )
        elif rotMode == 'rotz':
            self.action_rot_scale = 1./50
            self.action_space = Box(
                np.array([-1, -1, -1, -np.pi, -1]),
                np.array([1, 1, 1, np.pi, 1]),
            )
        elif rotMode == 'quat':
            self.action_space = Box(
                np.array([-1, -1, -1, 0, -1, -1, -1, -1]),
                np.array([1, 1, 1, 2*np.pi, 1, 1, 1, 1]),
            )
        else:
            self.action_space = Box(
                np.array([-1, -1, -1, -np.pi/2, -np.pi/2, 0, -1]),
                np.array([1, 1, 1, np.pi/2, np.pi/2, np.pi*2, 1]),
            )
        self.obj_and_goal_space = Box(
            np.array(obj_low),
            np.array(obj_high),
        )
        self.goal_space = Box(np.array(goal_low), np.array(goal_high))
        if self.obs_type == 'plain':
            self.observation_space = Box(
                np.hstack((self.hand_low, obj_low,)),
                np.hstack((self.hand_high, obj_high,)),
            )
        elif self.obs_type == 'with_goal':
            self.observation_space = Box(
                np.hstack((self.hand_low, obj_low, goal_low)),
                np.hstack((self.hand_high, obj_high, goal_high)),
            )
        else:
            raise NotImplementedError
        self.reset()

    def get_goal(self):
        return {
            'state_desired_goal': self._state_goal,
    }

    @property
    def model_name(self):
        return get_asset_full_path('sawyer_xyz/sawyer_door_lock.xml')

    def step(self, action):
        if self.rotMode == 'euler':
            action_ = np.zeros(7)
            action_[:3] = action[:3]
            action_[3:] = euler2quat(action[3:6])
            self.set_xyz_action_rot(action_)
        elif self.rotMode == 'fixed':
            self.set_xyz_action(action[:3])
        elif self.rotMode == 'rotz':
            self.set_xyz_action_rotz(action[:4])
        else:
            self.set_xyz_action_rot(action[:7])
        self.do_simulation([action[-1], -action[-1]])
        # The marker seems to get reset every time you do a simulation
        self._set_goal_marker(self._state_goal)
        ob = self._get_obs()
        reward, reachDist, pullDist = self.compute_reward(action, ob)
        self.curr_path_length +=1
        #info = self._get_info()
        if self.curr_path_length == self.max_path_length:
            done = True
        else:
            done = False
        info = {'reachDist': reachDist, 'goalDist': pullDist, 'epRew' : reward, 'pickRew':None, 'success': float(pullDist <= 0.05)}
        info['goal'] = self._state_goal
        return ob, reward, done, info

    def get_angle(self):
        return np.array([self.data.get_joint_qpos('joint')])

    def get_mocap_quat(self):
        return self.data.get_mocap_quat('mocap')

    def _get_obs(self):
        hand = self.get_endeff_pos()
        objPos = self.get_site_pos('lockStartLock')
        # angle = self.get_angle()
        flat_obs = np.concatenate((hand, objPos))
        if self.obs_type == 'with_goal_and_id':
            return np.concatenate([
                    flat_obs,
                    self._state_goal,
                    self._state_goal_idx
                ])
        elif self.obs_type == 'with_goal':
            return np.concatenate([
                    flat_obs,
                    self._state_goal
                ])
        elif self.obs_type == 'plain':
            return np.concatenate([flat_obs,])  # TODO ZP do we need the concat?
        else:
            return np.concatenate([flat_obs, self._state_goal_idx])

    def _get_obs_dict(self):
        hand = self.get_endeff_pos()
        objPos =  self.get_site_pos('lockStartLock')
        flat_obs = np.concatenate((hand, objPos))
        return dict(
            state_observation=flat_obs,
            state_desired_goal=self._state_goal,
            state_achieved_goal=objPos,
        )

    def _get_info(self):
        pass

    def _set_objCOM_marker(self):
        """
        This should be use ONLY for visualization. Use self._state_goal for
        logging, learning, etc.
        """
        objPos =  self.data.get_geom_xpos('handle')
        self.data.site_xpos[self.model.site_name2id('objSite')] = (
            objPos
        )

    def _set_goal_marker(self, goal):
        """
        This should be use ONLY for visualization. Use self._state_goal for
        logging, learning, etc.
        """
        self.data.site_xpos[self.model.site_name2id('goal_lock')] = (
            goal[:3]
        )
        self.data.site_xpos[self.model.site_name2id('goal_unlock')] = (
            np.array([10., 10., 10.])
        )

    def _set_obj_xyz_quat(self, pos, angle):
        quat = Quaternion(axis = [0,0,1], angle = angle).elements
        qpos = self.data.qpos.flat.copy()
        qvel = self.data.qvel.flat.copy()
        qpos[9:12] = pos.copy()
        qpos[12:16] = quat.copy()
        qvel[9:15] = 0
        self.set_state(qpos, qvel)

    def _set_obj_xyz(self, pos):
        qpos = self.data.qpos.flat.copy()
        qvel = self.data.qvel.flat.copy()
        qpos[9] = pos
        qvel[9] = 0
        self.set_state(qpos, qvel)

    def reset_model(self):
        self._reset_hand()
        door_pos = self.init_config['obj_init_pos']
        self.obj_init_pos = self.data.get_geom_xpos('lockGeom')
        self._state_goal = door_pos + np.array([0, -0.04, -0.03])
        if self.random_init:
            goal_pos = np.random.uniform(
                self.obj_and_goal_space.low,
                self.obj_and_goal_space.high,
                size=(self.obj_and_goal_space.low.size),
            )
            # self.obj_init_qpos = goal_pos[-1]
            door_pos = goal_pos
            self._state_goal = goal_pos + np.array([0, -0.04, -0.03])

        # self._set_obj_xyz(self.obj_init_qpos)
        # self.sim.model.body_pos[self.model.body_name2id('box')] = self.obj_init_pos
        # print(button_pos)
        self.sim.model.body_pos[self.model.body_name2id('door')] = door_pos
        self.sim.model.body_pos[self.model.body_name2id('lock')] = door_pos
        for _ in range(self.frame_skip):
            self.sim.step()
        self.obj_init_pos = self.data.get_geom_xpos('lockGeom')
        self._set_goal_marker(self._state_goal)
        self.maxPullDist = np.linalg.norm(self._state_goal - self.obj_init_pos)
        self.curr_path_length = 0
        #Can try changing this
        return self._get_obs()

    def _reset_hand(self):
        for _ in range(10):
            self.data.set_mocap_pos('mocap', self.hand_init_pos)
            self.data.set_mocap_quat('mocap', np.array([1, 0, 1, 0]))
            self.do_simulation([-1,1], self.frame_skip)
            #self.do_simulation(None, self.frame_skip)
        rightFinger, leftFinger = self.get_site_pos('rightEndEffector'), self.get_site_pos('leftEndEffector')
        self.init_fingerCOM  =  (rightFinger + leftFinger)/2
        self.reachCompleted = False

    def get_site_pos(self, siteName):
        _id = self.model.site_names.index(siteName)
        return self.data.site_xpos[_id].copy()

    def compute_rewards(self, actions, obsBatch):
        #Required by HER-TD3
        assert isinstance(obsBatch, dict) == True
        obsList = obsBatch['state_observation']
        rewards = [self.compute_reward(action, obs)[0] for  action, obs in zip(actions, obsList)]
        return np.array(rewards)

    def compute_reward(self, actions, obs):
        if isinstance(obs, dict): 
            obs = obs['state_observation']

        objPos = obs[3:6]

        rightFinger, leftFinger = self.get_site_pos('rightEndEffector'), self.get_site_pos('leftEndEffector')
        fingerCOM  =  (rightFinger + leftFinger)/2

        pullGoal = self._state_goal

        pullDist = np.linalg.norm(objPos - pullGoal)
        reachDist = np.linalg.norm(objPos - fingerCOM)
        # reachDistxy = np.linalg.norm(objPos[:-1] - fingerCOM[:-1])
        # zDist = np.linalg.norm(fingerCOM[-1] - self.init_fingerCOM[-1])
        # if reachDistxy < 0.05: #0.02
        #     reachRew = -reachDist
        # else:
        #     reachRew =  -reachDistxy - zDist
        reachRew = -reachDist

        def reachCompleted():
            if reachDist < 0.05:
                return True
            else:
                return False

        if reachCompleted():
            self.reachCompleted = True
        else:
            self.reachCompleted = False

        def pullReward():
            c1 = 1000 ; c2 = 0.01 ; c3 = 0.001
            # c1 = 10 ; c2 = 0.01 ; c3 = 0.001
            if self.reachCompleted:
                pullRew = 1000*(self.maxPullDist - pullDist) + c1*(np.exp(-(pullDist**2)/c2) + np.exp(-(pullDist**2)/c3))
                pullRew = max(pullRew,0)
                return pullRew
            else:
                return 0
            # pullRew = 1000*(self.maxPullDist - pullDist) + c1*(np.exp(-(pullDist**2)/c2) + np.exp(-(pullDist**2)/c3))
            # pullRew = max(pullRew,0)
            # return pullRew
        # pullRew = -pullDist
        pullRew = pullReward()
        reward = reachRew + pullRew# - actions[-1]/50
        # reward = pullRew# - actions[-1]/50
      
        return [reward, reachDist, pullDist] 

    def get_diagnostics(self, paths, prefix=''):
        statistics = OrderedDict()
        return statistics

    def log_diagnostics(self, paths = None, logger = None):
        pass
