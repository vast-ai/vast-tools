from autoscaler import InstanceSet
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--model", type=str)
parser.add_argument("--num_instances", type=int)
args = parser.parse_args()

if args.model:
    model = args.model
else:
    model = "hf-tgi-70"

if args.num_instances:
    num_instances = args.num_instances
else:
    num_instances = 1

i_set = InstanceSet(manage=False, model=model, backend="hf_tgi", streaming=True)
i_set.create_instances(num_instances=num_instances)
i_set.deconstruct()