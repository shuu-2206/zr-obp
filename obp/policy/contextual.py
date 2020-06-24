# Copyright (c) ZOZO Technologies, Inc. All rights reserved.
# Licensed under the Apache 2.0 License.

from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.optimize import minimize
from sklearn.utils import check_random_state

from ..utils import sigmoid


@dataclass
class BaseContextualPolicy(metaclass=ABCMeta):
    """Base class for contextual bandit policies.

    Parameters
    ----------
    dim: int
        Dimension of context vectors.

    n_actions: int
        Number of actions.

    len_list: int, default: 1
        Length of a list of recommended actions in each impression.
        When Open Bandit Dataset is used, 3 shouled be set.

    batch_size: int, default: 1
        Number of samples used in a batch parameter update.

    n_trial: int, default: 0
        Current number of trials in a bandit simulation.

    alpha_: float, default: 1.
        Prior parameter for the online logistic regression.

    lambda_: float, default: 1.
        Regularization hyperparameter for the online logistic regression.

    random_state: int, default: None
        Controls the random seed in sampling actions.

    policy_type: str, default: 'contextual'
        Type of bandit policy such as 'contextfree', 'contextual', and 'combinatorial'
    """
    dim: int
    n_actions: int
    len_list: int = 1
    batch_size: int = 1
    n_trial: int = 0
    alpha_: float = 1.
    lambda_: float = 1.
    random_state: Optional[int] = None
    policy_type: str = 'contextual'

    def __post_init__(self) -> None:
        """Initialize class."""
        self.random_ = check_random_state(self.random_state)
        self.alpha_list = self.alpha_ * np.ones(self.n_actions)
        self.lambda_list = self.lambda_ * np.ones(self.n_actions)
        self.action_counts = np.zeros(self.n_actions, dtype=int)
        self.reward_lists = [[] for i in np.arange(self.n_actions)]
        self.context_lists = [[] for i in np.arange(self.n_actions)]

    def initialize(self) -> None:
        """Initialize policy parameters."""
        self.n_trial = 0
        self.random_ = check_random_state(self.random_state)
        self.action_counts = np.zeros(self.n_actions, dtype=int)
        self.reward_lists = [[] for i in np.arange(self.n_actions)]
        self.context_lists = [[] for i in np.arange(self.n_actions)]

    @abstractmethod
    def select_action(self, context: np.ndarray) -> np.ndarray:
        """Select a list of actions."""
        pass

    @abstractmethod
    def update_params(self, action: float, reward: float, context: np.ndarray) -> None:
        """Update policy parameters."""
        pass


@dataclass
class LogisticEpsilonGreedy(BaseContextualPolicy):
    """Logistic Epsilon Greedy.

    Parameters
    ----------
    dim: int
        Dimension of context vectors.

    n_actions: int
        Number of actions.

    len_list: int, default: 1
        Length of a list of recommended actions in each impression.
        When Open Bandit Dataset is used, 3 shouled be set.

    batch_size: int, default: 1
        Number of samples used in a batch parameter update.

    n_trial: int, default: 0
        Current number of trials in a bandit simulation.

    alpha_: float, default: 1.
        Prior parameter for the online logistic regression.

    lambda_: float, default: 1.
        Regularization hyperparameter for the online logistic regression.

    random_state: int, default: None
        Controls the random seed in sampling actions.

    policy_type: str, default: 'contextual'
        Type of bandit policy such as 'contextfree', 'contextual', and 'combinatorial'.

    epsilon: float, default: 0.
        Exploration hyperparameter that must take value in the range of [0., 1.].

    policy_name: str, default: f'logistic_egreedy_{epsilon}'.
        Name of bandit policy.
    """
    epsilon: float = 0.
    policy_name: str = f'logistic_egreedy_{epsilon}'

    assert 0 <= epsilon <= 1, f'epsilon must be in [0, 1], but {epsilon} is set.'

    def __post_init__(self) -> None:
        """Initialize class."""
        super().__post_init__()
        self.model_list = [
            MiniBatchLogisticRegression(
                lambda_=self.lambda_list[i], alpha=self.alpha_list[i], dim=self.dim)
            for i in np.arange(self.n_actions)]
        self.reward_lists = [[] for i in np.arange(self.n_actions)]
        self.context_lists = [[] for i in np.arange(self.n_actions)]

    def select_action(self, context: np.ndarray) -> np.ndarray:
        """Select action for new data.

        Parameters
        ----------
        context: array
            Observed context vector.

        Returns
        ----------
        selected_actions: array
            List of selected actions.
        """
        if self.action_counts.min() == 0:
            return self.random_.choice(self.n_actions, size=self.len_list, replace=False)
        else:
            if self.random_.rand() > self.epsilon:
                theta = np.array([model.predict_proba(context) for model in self.model_list]).flatten()
                unsorted_max_arms = np.argpartition(-theta, self.len_list)[:self.len_list]
                return unsorted_max_arms[np.argsort(-theta[unsorted_max_arms])]
            else:
                return self.random_.choice(self.n_actions, size=self.len_list, replace=False)

    def update_params(self, action: int, reward: float, context: np.ndarray) -> None:
        """Update policy parameters.

        Parameters
        ----------
        action: int
            Selected action by the policy.

        reward: float
            Observed reward for the chosen action and position.

        context: array
            Observed context vector.
        """
        self.n_trial += 1
        self.action_counts[action] += 1
        self.reward_lists[action].append(reward)
        self.context_lists[action].append(context)
        if self.n_trial % self.batch_size == 0:
            for action, model in enumerate(self.model_list):
                if not len(self.reward_lists[action]) == 0:
                    model.fit(X=np.concatenate(self.context_lists[action], axis=0),
                              y=np.array(self.reward_lists[action]))
            self.reward_lists = [[] for i in np.arange(self.n_actions)]
            self.context_lists = [[] for i in np.arange(self.n_actions)]


@dataclass
class LogisticUCB(BaseContextualPolicy):
    """Logistic Upper Confidence Bound.

    Parameters
    ----------
    dim: int
        Dimension of context vectors.

    n_actions: int
        Number of actions.

    len_list: int, default: 1
        Length of a list of recommended actions in each impression.
        When Open Bandit Dataset is used, 3 shouled be set.

    batch_size: int, default: 1
        Number of samples used in a batch parameter update.

    n_trial: int, default: 0
        Current number of trials in a bandit simulation.

    alpha_: float, default: 1.
        Prior parameter for the online logistic regression.

    lambda_: float, default: 1.
        Regularization hyperparameter for the online logistic regression.

    random_state: int, default: None
        Controls the random seed in sampling actions.

    policy_type: str, default: 'contextual'
        Type of bandit policy such as 'contextfree', 'contextual', and 'combinatorial'.

    epsilon: float, default: 0.
        Exploration hyperparameter that must take value in the range of [0., 1.].

    policy_name: str, default: f'logistic_ucb_{epsilon}'.
        Name of bandit policy.

    References
    ----------
    Lihong Li, Wei Chu, John Langford, and Robert E Schapire.
    "A Contextual-bandit Approach to Personalized News Article Recommendation," 2010.
    """
    epsilon: float = 0.
    policy_name: str = f'logistic_ucb_{epsilon}'

    assert 0 <= epsilon <= 1, f'epsilon must be in [0, 1], but {epsilon} is set.'

    def __post_init__(self) -> None:
        """Initialize class."""
        super().__post_init__()
        self.model_list = [
            MiniBatchLogisticRegression(
                lambda_=self.lambda_list[i], alpha=self.alpha_list[i], dim=self.dim)
            for i in np.arange(self.n_actions)]
        self.reward_lists = [[] for i in np.arange(self.n_actions)]
        self.context_lists = [[] for i in np.arange(self.n_actions)]

    def select_action(self, context: np.ndarray) -> np.ndarray:
        """Select action for new data.

        Parameters
        ----------
        context: array
            Observed context vector.

        Returns
        ----------
        selected_actions: array
            List of selected actions.
        """
        if self.action_counts.min() == 0:
            return self.random_.choice(self.n_actions, size=self.len_list, replace=False)
        else:
            theta = np.array([model.predict_proba(context)
                              for model in self.model_list]).flatten()
            std = np.array([np.sqrt(np.sum((model._q ** (-1)) * (context ** 2)))
                            for model in self.model_list]).flatten()
            ucb_score = theta + self.epsilon * std
            unsorted_max_arms = np.argpartition(-ucb_score, self.len_list)[:self.len_list]
            return unsorted_max_arms[np.argsort(-ucb_score[unsorted_max_arms])]

    def update_params(self, action: int, reward: float, context: np.ndarray) -> None:
        """Update policy parameters.

        Parameters
        ----------
        action: int
            Selected action by the policy.

        reward: float
            Observed reward for the chosen action and position.

        context: array
            Observed context vector.
        """
        self.n_trial += 1
        self.action_counts[action] += 1
        self.reward_lists[action].append(reward)
        self.context_lists[action].append(context)
        if self.n_trial % self.batch_size == 0:
            for action, model in enumerate(self.model_list):
                if not len(self.reward_lists[action]) == 0:
                    model.fit(X=np.concatenate(self.context_lists[action], axis=0),
                              y=np.array(self.reward_lists[action]))
            self.reward_lists = [[] for i in np.arange(self.n_actions)]
            self.context_lists = [[] for i in np.arange(self.n_actions)]


@dataclass
class LogisticTS(BaseContextualPolicy):
    """Logistic Thompson Sampling.

    Parameters
    ----------
    dim: int
        Dimension of context vectors.

    n_actions: int
        Number of actions.

    len_list: int, default: 1
        Length of a list of recommended actions in each impression.
        When Open Bandit Dataset is used, 3 shouled be set.

    batch_size: int, default: 1
        Number of samples used in a batch parameter update.

    n_trial: int, default: 0
        Current number of trials in a bandit simulation.

    alpha_: float, default: 1.
        Prior parameter for the online logistic regression.

    lambda_: float, default: 1.
        Regularization hyperparameter for the online logistic regression.

    random_state: int, default: None
        Controls the random seed in sampling actions.

    policy_type: str, default: 'contextual'
        Type of bandit policy such as 'contextfree', 'contextual', and 'combinatorial'.

    policy_name: str, default: f'logistic_ts'.
        Name of bandit policy.

    References
    ----------
    Olivier Chapelle and Lihong Li.
    "An empirical evaluation of thompson sampling," 2011.
    """
    policy_name: str = 'logistic_ts'

    def __init__(self) -> None:
        """Initialize class."""
        super().__post_init__()
        self.model_list = [
            MiniBatchLogisticRegression(
                lambda_=self.lambda_list[i], alpha=self.alpha_list[i], dim=self.dim)
            for i in np.arange(self.n_actions)]
        self.reward_lists = [[] for i in np.arange(self.n_actions)]
        self.context_lists = [[] for i in np.arange(self.n_actions)]

    def select_action(self, context: np.ndarray) -> np.ndarray:
        """Select action for new data.

        Parameters
        ----------
        context: array
            Observed context vector.

        Returns
        ----------
        selected_actions: array
            List of selected actions.
        """
        if self.action_counts.min() == 0:
            return self.random_.choice(self.n_actions, size=self.len_list, replace=False)
        else:
            theta = np.array([model.predict_proba_with_sampling(context)
                              for model in self.model_list]).flatten()
            unsorted_max_arms = np.argpartition(-theta, self.len_list)[:self.len_list]
            return unsorted_max_arms[np.argsort(-theta[unsorted_max_arms])]

    def update_params(self, action: int, reward: float, context: np.ndarray) -> None:
        """Update policy parameters.

        Parameters
        ----------
        action: int
            Selected action by the policy.

        reward: float
            Observed reward for the chosen action and position.

        context: array
            Observed context vector.
        """
        self.n_trial += 1
        self.action_counts[action] += 1
        self.reward_lists[action].append(reward)
        self.context_lists[action].append(context)
        if self.n_trial % self.batch_size == 0:
            for action, model in enumerate(self.model_list):
                if not len(self.reward_lists[action]) == 0:
                    model.fit(X=np.concatenate(self.context_lists[action], axis=0),
                              y=np.array(self.reward_lists[action]))
            self.reward_lists = [[] for i in np.arange(self.n_actions)]
            self.context_lists = [[] for i in np.arange(self.n_actions)]


@dataclass
class MiniBatchLogisticRegression:
    """MiniBatch Online Logistic Regression Model."""
    lambda_: float
    alpha: float
    dim: int

    def __post_init__(self) -> None:
        """Initialize Class."""
        self._m = np.zeros(self.dim)
        self._q = np.ones(self.dim) * self.lambda_

    def loss(self, w: np.ndarray, *args) -> float:
        """Calculate loss function."""
        X, y = args
        return 0.5 * (self._q * (w - self._m)).dot(w - self._m) + np.log(1 + np.exp(-y * w.dot(X.T))).sum()

    def grad(self, w: np.ndarray, *args) -> np.ndarray:
        """Calculate gradient."""
        X, y = args
        return self._q * (w - self._m) + (-1) * (((y * X.T) / (1. + np.exp(y * w.dot(X.T)))).T).sum(axis=0)

    def sample(self) -> np.ndarray:
        """Sample coefficient vector from the prior distribution."""
        return self.random_.normal(self._m, self.sd(), size=self.dim)

    def fit(self, X: np.ndarray, y: np.ndarray):
        """Update coefficient vector by the mini-batch data."""
        self._m = minimize(self.loss, self._m, args=(X, y), jac=self.grad, method="L-BFGS-B",
                           options={'maxiter': 20, 'disp': False}).x
        P = (1 + np.exp(1 + X.dot(self._m))) ** (-1)
        self._q = self._q + (P * (1 - P)).dot(X ** 2)

    def sd(self) -> np.ndarray:
        """Standard deviation for the coefficient vector."""
        return self.alpha * (self._q)**(-1.0)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Predict extected probability by the expected coefficient."""
        return sigmoid(X.dot(self._m))

    def predict_proba_with_sampling(self, X: np.ndarray) -> np.ndarray:
        """Predict extected probability by the sampled coefficient."""
        return sigmoid(X.dot(self.sample()))