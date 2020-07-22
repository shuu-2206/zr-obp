import argparse
from pathlib import Path
import yaml

import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.experimental import enable_hist_gradient_boosting
from sklearn.ensemble import HistGradientBoostingClassifier

from custom_dataset import OBDWithInteractionFeatures
from obp.policy import LogisticTS, LogisticEpsilonGreedy, LogisticUCB
from obp.simulator import run_bandit_simulation
from obp.ope import (
    RegressionModel,
    OffPolicyEvaluation,
    InverseProbabilityWeighting,
    DirectMethod,
    DoublyRobust
)


with open('./conf/lightgbm.yaml', 'rb') as f:
    hyperparams = yaml.safe_load(f)['model']

counterfactual_policy_dict = dict(
    logistic_egreedy=LogisticEpsilonGreedy,
    logistic_ts=LogisticTS,
    logistic_ucb=LogisticUCB
)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='run off-policy evaluation of a counterfactual logistic bandit policy.')
    parser.add_argument('--context_set', type=str, choices=['1', '2'], required=True,
                        help='context sets for logistic bandit policies.')
    parser.add_argument('--counterfactual_policy', type=str,
                        choices=['logistic_egreedy', 'logistic_ts', 'logistic_ucb'], required=True,
                        help='counterfacutual policy, logistic_egreedy, logistic_ts, or logistic_ucb.')
    parser.add_argument('--epsilon', type=float, default=0.1,
                        help='exploration hyperparameter for logistic bandit policies. must be between 0 and 1.')
    parser.add_argument('--behavior_policy', type=str, choices=['bts', 'random'], required=True,
                        help='behavior policy, bts or random.')
    parser.add_argument('--campaign', type=str, choices=['all', 'men', 'women'], required=True,
                        help='campaign name, men, women, or all.')
    parser.add_argument('--random_state', type=int, default=12345)
    args = parser.parse_args()
    print(args)

    context_set = args.context_set
    counterfactual_policy = args.counterfactual_policy
    epsilon = args.epsilon
    behavior_policy = args.behavior_policy
    campaign = args.campaign
    random_state = args.random_state

    obd = OBDWithInteractionFeatures(
        behavior_policy=behavior_policy,
        campaign=campaign,
        data_path=Path('.').resolve().parents[1] / 'obd',
        context_set=context_set
    )

    # hyperparameters for logistic bandit policies
    kwargs = dict(
        n_actions=obd.n_actions,
        len_list=obd.len_list,
        dim=obd.dim_context,
        random_state=random_state
    )
    if counterfactual_policy != 'logistic_ts':
        kwargs['epsilon'] = epsilon
    policy = counterfactual_policy_dict[counterfactual_policy](**kwargs)
    policy_name = f'{policy.policy_name}_{context_set}'

    # obtain batch logged bandit feedback generated by behavior policy
    bandit_feedback = obd.obtain_batch_bandit_feedback()
    # ground-truth policy value of the random policy
    # , which is the empirical mean of the factual (observed) rewards
    ground_truth = bandit_feedback['reward'].mean()

    # a base ML model for regression model used in Direct Method and Doubly Robust
    base_model = CalibratedClassifierCV(HistGradientBoostingClassifier(**hyperparams))
    # run a counterfactual bandit algorithm on logged bandit feedback data
    selected_actions = run_bandit_simulation(bandit_feedback=bandit_feedback, policy=policy)
    # estimate the policy value of a given counterfactual algorithm by the three OPE estimators.
    ope = OffPolicyEvaluation(
        bandit_feedback=bandit_feedback,
        regression_model=RegressionModel(base_model=base_model),
        action_context=obd.action_context,
        ope_estimators=[InverseProbabilityWeighting(), DirectMethod(), DoublyRobust()]
    )
    estimated_policy_value, estimated_interval = ope.summarize_off_policy_estimates(selected_actions=selected_actions)

    # estimated policy value and that realtive to that of the behavior policy
    print('=' * 70)
    print(f'random_state={random_state}: counterfactual policy={policy_name}')
    print('-' * 70)
    estimated_policy_value['relative_estimated_policy_value'] = estimated_policy_value.estimated_policy_value / ground_truth
    print(estimated_policy_value)
    print('=' * 70)

    # save counterfactual policy evaluation results in `./logs` directory
    save_path = Path('./logs') / behavior_policy / campaign / 'cf_policy_selection'
    save_path.mkdir(exist_ok=True, parents=True)
    pd.DataFrame(estimated_policy_value).to_csv(save_path / f'{policy_name}.csv')
    # save visualization of the off-policy evaluation results in `./logs` directory
    ope.visualize_off_policy_estimates(
        selected_actions=selected_actions,
        fig_dir=save_path,
        fig_name=f'{policy_name}.png'
    )