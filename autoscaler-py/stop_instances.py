from ..autoscaler import InstanceSet

def main():
    instances = InstanceSet(manage=False)
    instances.stop_all_instances()
    instances.deconstruct()

if __name__ == "__main__":
	main()
