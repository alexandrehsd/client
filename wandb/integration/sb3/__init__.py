"""W&B callback for sb3

Really simple callback to get logging for each tree

Example usage:

```
import gym
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import DummyVecEnv
from wandb.integration.sb3 import WandbCallback
import wandb

def make_env():
    env = gym.make("CartPole-v1")
    env = gym.wrappers.Monitor(env, f"videos", force=True)      # record videos
    env = gym.wrappers.RecordEpisodeStatistics(env) # record stats such as returns
    return env

config = {
    "policy_type": 'MlpPolicy',
    "total_timesteps": 25000
}

wandb.init(
    name="my_ppo_experiment",
    project="sb3",
    config=config,
    allow_val_change=True, # auto-log the model's hyperparams
    sync_tensorboard=True, # auto-upload metrics
    monitor_gym=True,  # auto-upload the videos of agents playing the game
    save_code=True,  
)

env = DummyVecEnv([make_env])
model = PPO(config['policy_type'], env, verbose=1, tensorboard_log=f"runs/ppo")
model.learn(total_timesteps=config['total_timesteps'],
    callback=WandbCallback(
        gradient_save_freq=100,
        model_save_freq=1000,
        model_save_path="./models",
))
```
"""

import os

from stable_baselines3.common.callbacks import BaseCallback
import wandb


class WandbCallback(BaseCallback):
    """ Log SB3 experiments to Weights and Biases

        - Added model tracking and uploading
        - Added complete hyperparameters recording
        - Added gradient logging
    Arguments:
        verbose - The verbosity of sb3 output
        model_save_freq - Frequency to save the model
        model_save_path - Path to the folder where the model will be saved
        gradient_save_freq - Frequency to log gradient. If set 0, then gradients are not logged
    """

    def __init__(
        self,
        verbose=0,
        model_save_freq=1000,
        model_save_path=None,
        gradient_save_freq=0,
    ):
        super(WandbCallback, self).__init__(verbose)
        assert self._wandb.run is not None, "no wandb run detected; use `wandb.init()` to initialize a run"
        self.model_save_freq = model_save_freq
        self.model_save_path = model_save_path
        self.gradient_save_freq = gradient_save_freq
        # Create folder if needed
        if self.model_save_path is not None:
            os.makedirs(self.model_save_path, exist_ok=True)
            self.path = os.path.join(self.model_save_path, "model.zip")

    def _init_callback(self) -> None:
        d = {}
        for key in self.model.__dict__:
            if key in wandb.config:
                continue
            if type(self.model.__dict__[key]) in [float, int, str]:
                d[key] = self.model.__dict__[key]
            else:
                d[key] = str(self.model.__dict__[key])
        if self.gradient_save_freq > 0:
            wandb.watch(self.model.policy, log_freq=self.gradient_save_freq, log="all")
        wandb.config.update(d)

    def _on_step(self) -> bool:
        if self.model_save_path is not None:
            if self.n_calls % self.model_save_freq == 0:
                self.model.save(self.path)
                wandb.save(self.path)
                if self.verbose > 1:
                    print("Saving model checkpoint to", self.path)
        return True
