"""Simple 2D environment containing a point and a goal location."""
from concurrent.futures import process
import math

import akro
import numpy as np
import circle_fit as cf
import pandas as pd 
from garage import Environment, EnvSpec, EnvStep, StepType
import random 
from gym.spaces import Box, Discrete
import csv 
import trackml.dataset
import json


with open("/home/lhv14/module_map.json", 'r') as j:
     module_map = json.loads(j.read())

remap_modules_dic = ''
with open(r'/home/lhv14/remap_modules.txt','r') as f:
         for i in f.readlines():
            remap_modules_dic=i #string
remap_modules_dic = eval(remap_modules_dic) # this is orignal dict with instace dict



detector = pd.read_csv('/home/lhv14/exatrkx/Tracking-ML-Exa.TrkX/data/detectors.csv')
detector['new_module_id'] = detector['volume_id']*100000000+ detector['layer_id']*100000 + detector['module_id']
detector['cr'] = np.sqrt(detector.cx**2 + detector.cy**2)/10
detector['cz'] = detector['cz']/10
detector['cr'] = detector['cr']/10
zlist = detector['cz'].tolist()
rlist = detector['cr'].tolist() 
mods = detector.set_index(['volume_id', 'layer_id', 'module_id']).index

detector['discrete_module_id'] = [remap_modules_dic[val] for val in mods]

prefix = '/home/lhv14/exatrkx/Tracking-ML-Exa.TrkX/alldata/train_1/event000001000'
f = open("garage_outputs.csv", "w")
writer = csv.writer(f)
writer.writerow(["filenumber", "particle_id", "mc_z", "mc_r", "pred_z", "pred_r", "action_z", "action_r"])




class ModuleTrackMLEnv(Environment):
    """A simple 2D point environment.

    Args:
        goal (np.ndarray): A 2D array representing the goal position
        arena_size (float): The size of arena where the point is constrained
            within (-arena_size, arena_size) in each dimension
        done_bonus (float): A numerical bonus added to the reward
            once the point as reached the goal
        never_done (bool): Never send a `done` signal, even if the
            agent achieves the goal
        max_episode_length (int): The maximum steps allowed for an episode.

    """

    def __init__(self,
                # goal=np.array((1., 1.), dtype=np.float32),
                 arena_size=5.,
                 done_bonus=0.,
                 never_done=False,
                 max_episode_length=500):
        #goal = np.array(goal, dtype=np.float32)
        #self._goal = goal
        self._done_bonus = done_bonus
        self._never_done = never_done
        self._arena_size = arena_size
        self._total_step_cnt = 0 
        self.new_count = 0 
        self.done_visual = False 
        self.file_counter = 0 
        #self.event = pd.read_hdf('~/gnnfiles/data/ntuple_PU200_numEvent1000/ntuple_PU200_event0.h5')
        #self.event = pd.read_hdf('/media/lucas/MicroSD/ntuple_PU200_numEvent1000/ntuple_PU200_event0.h5')
        #self.event['z'] = np.abs(self.event['z'])
        self.average_reward = 0 
        self.hit_buffer = []
        self.dz_buffer = []
        self.dr_buffer = []


       # assert ((goal >= -arena_size) & (goal <= arena_size)).all()

        self._step_cnt = None
        self._max_episode_length = max_episode_length
        self._visualize = False

        #self._point = np.zeros_like(self._goal)
        #self._task = {'goal': self._goal}
        self._observation_space = akro.Box(low=np.array([-300, 0, 0]), high=np.array([300, 30, 18728]), dtype=np.float32)

        self._action_space = akro.Discrete(18728)

        self._spec = EnvSpec(action_space=self.action_space,
                             observation_space=self.observation_space,
                             max_episode_length=max_episode_length)

        self.record_z = [] 
        self.record_r = []
        self.record_pid = []
        self.record_event_counter = [] 
        self.record_reward = [] 
        self.record_a0 = [] 
        self.record_a1 = [] 
        self.record_filenumber = [] 

    @property
    def action_space(self):
        """akro.Space: The action space specification."""
        return self._action_space

    @property
    def observation_space(self):
        """akro.Space: The observation space specification."""
        return self._observation_space

    @property
    def spec(self):
        """EnvSpec: The environment specification."""
        return self._spec

    @property
    def render_modes(self):
        """list: A list of string representing the supported render modes."""
        return [
            'ascii',
        ]

    def reset(self):
        """Reset the environment.

        Returns:
            numpy.ndarray: The first observation conforming to
                `observation_space`.
            dict: The episode-level information.
                Note that this is not part of `env_info` provided in `step()`.
                It contains information of he entire episode， which could be
                needed to determine the first action (e.g. in the case of
                goal-conditisoned or MTRL.)

        """
        
        if self._total_step_cnt%100 ==0: 
            self.file_counter += 1 
            self.event = process_trackml(self.file_counter, pt_min=2)
            #self.event['z'] = np.abs(self.event['z'])
            print("jumping file")
      

        random_particle_id = random.choice(self.event.particle_id.values)
        self.particle = self.event[self.event['particle_id']==random_particle_id]

        self.original_pid = random_particle_id
        start_hit = self.particle.iloc[0,:]
        #next_hit = self.particle.iloc[1,:]
        self._point = start_hit[['z', 'r']].values 
        self.dr_buffer = []
        self.dz_buffer = []

        self.num_track_hits = 1
        self.state = start_hit.squeeze(axis=0) 

        self.dr_buffer.append(0)
        self.dz_buffer.append(0)
      
        row = pd.DataFrame({'filenumber': [self.file_counter], 
        'particle_id': [self.original_pid], 
        'mc_z': [start_hit.z],
        'mc_r' : [start_hit.r],
        'pred_z': [start_hit.z],
        'pred_r': [start_hit.r],
        'action_z': [np.nan],
        'action_r': [np.nan]})
        row.to_csv(f, mode='a', header=None, index=None)

        observation=self._point

        
        self.state = [start_hit.z, start_hit.r, start_hit.discrete_module_id]
        self.module_id = start_hit.new_module_id
        self._step_cnt = 0
        self.original_particle = self.event[self.event['particle_id']==self.original_pid].reset_index()

        return self.state, dict(something=[1,1])

    def step(self, action):
        """Step the environment.

        Args:
            action (np.ndarray): An action provided by the agent.

        Returns:
            EnvStep: The environment step resulting from the action.

        Raises:
            RuntimeError: if `step()` is called after the environment
            has been
                constructed and `reset()` has not been called.

        """
        if self._step_cnt is None:
            raise RuntimeError('reset() must be called before step()!')
        
        self.new_count += 1 

        # enforce action space
        a = action.copy()  # NOTE: we MUST copy the action before modifying it

        module = detector[detector['discrete_module_id']==a]


        #a_clipped = np.clip(a, self.action_space.low, self.action_space.high)
        #naive_estimate = self._point + np.array([max(0, self.dz_buffer[-1]),  max(0, self.dr_buffer[-1])])
        #nearest_module, module_id = find_nearest_module(naive_estimate[0], naive_estimate[1], self.module_id)

        predicted_point_z = module.cz.values[0]
        predicted_point_r = module.cr.values[0]




        #naive_estimate = self._point + np.array([max(0, self.dz_buffer[-1]),  max(0, self.dr_buffer[-1])])
        #nearest_module, module_id = find_nearest_module(naive_estimate[0], naive_estimate[1], self.module_id)
        #nearest_module_point = detector[detector['new_module_id'] ==  nearest_module][['cz', 'cr']].values.flatten()
        #self.module_id = module_id 

        #predicted_point_z = np.clip(naive_estimate[0] +  a_clipped[0] , -300, 300)
        #predicted_point_r = np.clip(naive_estimate[1] +  a_clipped[1], 0, 30)


        predicted_point = [predicted_point_z, predicted_point_r]

        #new_module = find_nearest_module(predicted_point_z, predicted_point_r, self.module_id)
        #adjusted_predicted_point = detector[detector['new_module_id'] ==  new_module][['cz', 'cr']].values.flatten()
        #print(predicted_point)
        #self.module_id = new_module 

        if self._visualize:
            print(self.render('ascii'))

        #mag_dist_prev_hit = np.sqrt(self.state.z-new_hit.z)**2 + (self.state.r-new_hit.r)**2
        self.previous_state = self.state
        #self.state = np.concatenate(predicted_point, [a])
        self.state = np.array([predicted_point_z, predicted_point_r, a])

       # print(predicted_point, a, self.state)

        next_index = self.num_track_hits + 1 
        if next_index > len(self.original_particle) -1: 
            next_index = len(self.original_particle) - 1
        next_hit = self.original_particle.loc[next_index,: ]
        #self.hit_buffer.append([predicted_point_z, predicted_point_r])

        #reward given based on how close this new hit was to the next hit in the df 
        #distance = np.sqrt((new_hit.z - next_hit.z)**2 + (new_hit.r - next_hit.r)**2)
        distance = np.sqrt((predicted_point_z-next_hit.z)**2 + (predicted_point_r-next_hit.r)**2)

        #print(predicted_point_z, distance)
        #print(distance)
        ##reward = -distance
        correct_module = next_hit['discrete_module_id']
        allowed_modules = module_map[str(int(self.previous_state[2]))]

        #reward = - np.abs(correct_module - a)
        reward = distance 
        if a not in allowed_modules: 
            reward = -100

        self.num_track_hits += 1 
    

        dr = self.state[1] - self.previous_state[1]
        dz = self.state[0] - self.previous_state[0]
       
        self.dr_buffer.append(dr)
        self.dz_buffer.append(dz)
      
        self._step_cnt += 1
        self._total_step_cnt += 1
  

        row = pd.DataFrame({'filenumber': [self.file_counter], 
        'particle_id': [self.original_pid], 
        'mc_z': [next_hit.z], 
        'mc_r' : [next_hit.r], 
        'pred_z': [predicted_point_z], 
        'pred_r': [predicted_point_r]
        })
        #'action_z': [a[0]], 
        #'action_r': [a[1]] })
        row.to_csv(f, mode='a', header=None, index=None)


        #stopping = np.mean(np.abs(np.diff(self.dz_buffer[-4:]))) + np.mean(np.abs(np.diff(self.dr_buffer[-4:])))
       
        if self.num_track_hits > 6: 
        #if a[2] > 0.5:
            done = True 
        else: 
            done = False 
            #self.episode_counter +=1 

        self._point = predicted_point
        #print(self._point, "\n")
        observation = self.state
        step_type = StepType.get_step_type(
            step_cnt=self._step_cnt,
            max_episode_length=self._max_episode_length,
            done=done)
 
        if step_type in (StepType.TERMINAL, StepType.TIMEOUT):
            self._step_cnt = None


        self.average_reward = (self.average_reward + reward)/2
        #if self._total_step_cnt%100==0: 
        #    print(self.average_reward)

        return EnvStep(env_spec=self.spec,
                       action=action,
                       reward=reward,
                       observation=observation,
                       env_info={
                           #'task': self._task,
                        'filenumber': self.file_counter, 
                        'particle_id': self.original_pid, 
                        'mc_z': next_hit.z, 
                        'mc_r' : next_hit.r, 
                        'pred_z': predicted_point_z, 
                        'pred_r': predicted_point_r, 
                 #       'action_z': a[0], 
                 #       'action_r': a[1]
                           #'success': succ
                       },
                       step_type=step_type)

    def render(self, mode):
        """Renders the environment.

        Args:
            mode (str): the mode to render with. The string must be present in
                `self.render_modes`.

        Returns:
            str: the point and goal of environment.

        """
        #return f'Point: {self._point}, Goal: {self._goal}'
        return self._point 

    def visualize(self):
        """Creates a visualization of the environment."""
        #self._visualize = True
        #print(self.render('ascii'))
        #visualise(self.state.r, )
        #visualise() 
        #wrap(self.event, r, z, pids, self.original_pid)
        print(self.original_pid)
        #print("i now visualise")

    def my_visualise(self): 
            print("now calling visualise")
            #wrap(self.event)
            #visualise(self.event, self.record_pid, self.record_r, self.record_z)
        
    def close(self):
        """Close the env."""

    # pylint: disable=no-self-use
    def sample_tasks(self, num_tasks):
        """Sample a list of `num_tasks` tasks.

        Args:
            num_tasks (int): Number of tasks to sample.

        Returns:
            list[dict[str, np.ndarray]]: A list of "tasks", where each task is
                a dictionary containing a single key, "goal", mapping to a
                point in 2D space.

        """
        #goals = np.random.uniform(-2, 2, size=(num_tasks, 2))
        #tasks = [{'goal': goal} for goal in goals]
        #return tasks
        return 0 


    def set_task(self, task):
        """Reset with a task.

        Args:
            task (dict[str, np.ndarray]): A task (a dictionary containing a
                single key, "goal", which should be a point in 2D space).

        """
        #self._task = task
        #self._goal = task['goal']
        x = 10 

    def dump_summary(self):
        print("dr:   ", "\n dz:    " ) 

def process_trackml(filenumber, pt_min): 
    prefix = '/home/lhv14/exatrkx/Tracking-ML-Exa.TrkX/alldata/train_1/event00000'+str(1000+filenumber)

    hits, particles, truth = trackml.dataset.load_event(
            prefix, parts=['hits', 'particles', 'truth'])
    
    hits['r'] = np.sqrt(hits.x**2 + hits.y**2)/10

    pt = np.sqrt(particles.px**2 + particles.py**2)
    particles['pt'] = pt

     # Applies pt cut, removes all noise hits.
    #particles = particles[pt > pt_min]
    truth = (truth[['hit_id', 'particle_id']]
             .merge(particles[['particle_id', 'pt', 'nhits']], on='particle_id'))
    # Calculate derived hits variables
    #r = np.sqrt(hits.x**2 + hits.y**2)
    phi = np.arctan2(hits.y, hits.x)
    # Select the data columns we need
    hits = (hits[['hit_id', 'z', 'r', 'layer_id', 'volume_id', 'module_id']]
            .assign(phi=phi)
            .merge(truth[['hit_id', 'particle_id', 'pt', 'nhits']], on='hit_id'))
    # Remove duplicate hits
    #hits = hits.loc[hits.groupby(['particle_id', 'layer_id']).r.idxmin().values]
    #hits['r'] = r/10
    hits['z'] = hits['z']/10
    hits = hits.sort_values('r')
    hits['new_module_id'] = hits['volume_id']*100000000+ hits['layer_id']*100000 + hits['module_id']

    #hits.to_csv('test_these_hits.csv')

    #hits = hits[hits['volume_id'] < 10] 
    #nh = hits.groupby('particle_id').agg('count').iloc[:,0]
        # only pick the pids that has a certain number of hits 
    #hits = hits[hits['particle_id'].isin(np.array(nh[nh > 7].index))]
    hits = hits[hits['nhits'] > 7]
    mods = hits.set_index(['volume_id', 'layer_id', 'module_id']).index

    hits['discrete_module_id'] = [remap_modules_dic[val] for val in mods]
    
    return hits

def find_nearest_module(pred_z, pred_r, prev_module):

    #only select from modules that are connected to the previous module 
    #t = module_map[prev_module]

    #json only supports strings as keys 
    #prev_module_pos = 
    compatible_modules = detector[detector['new_module_id'].isin(module_map[str(int(prev_module))])]
    # only radially outwards
    #print(compatible_modules)
    #compatible_modules = compatible_modules[(np.abs(compatible_modules['cz']) > np.abs((pred_z-10))) & (compatible_modules['cr'] > (pred_r-1))]
     

    #print(compatible_modules[['cz', 'cr']])
    zlist = compatible_modules.cz.values
    rlist = compatible_modules.cr.values

    distances = np.sqrt((zlist-pred_z)**2+(rlist - pred_r)**2) 
    index = np.argmin(distances)
    #print(compatible_modules['new_module_id'].values[index])
    module = detector.iloc[index, ]
    module_position = module[['cz', 'cr']].values
    module_id = module.new_module_id
    
    #return compatible_modules['new_module_id'].values[index]

    return module_position, module_id

def find_nearest_module_by_position(z, r): 
    distances = np.sqrt((zlist-z)**2+(rlist - r)**2) 
    #print(distances)
    index = np.argmin(distances)
    module_position = detector.iloc[index, ][['cz', 'cr']].values
    return module_position
