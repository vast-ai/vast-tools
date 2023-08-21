import random
import time
from threading import Thread, Lock, Event
from client import Client

PROMPTS = [ "Yesterday I woke up and I saw that my dog was missing. This made me think that ",
            "I have been thinking a lot about the question of what the best movie of all time is. There are a lot of different ways to approach this question, but for me the most important factor is how exciting it is. With that in mind, I would say the best movie is: ",
            "I hope that one day humans will be able to live on another planet. This planet is great, but there are many issues with it, and it is not clear how long it will last. Other planets are much harder to live on, so it will be hard for other humans to live on them, but in a worst case scenario it would be great to have the option to live on another planet. I think that in order for humans to be able to live on another planet, the following needs to happen: ",
            "In the realm of possibilities, where ideas take shape and dreams find expression, there exists a tapestry of thoughts that intertwine and weave the fabric of our understanding. From the cosmic dance of stars in the night sky to the gentle rustle of leaves in an ancient forest, the universe unfolds its mysteries before our curious gaze. In this vast expanse, the human spirit embarks on a quest for knowledge, driven by an insatiable thirst to unravel the enigma of existence. As we navigate the corridors of time, we are bound by the threads of history that have shaped civilizations and cultures across continents. From the pyramids of Egypt that stand as sentinel monuments to human ingenuity to the intricate temples of Angkor Wat that speak of devotion carved in stone, the echoes of the past reverberate in the present, reminding us of the enduring legacy of our predecessors. The passage of time has ushered in waves of change, ushering in revolutions that have redefined the course of human progress. The clanking gears of the Industrial Revolution gave rise to a new era of mechanization, propelling society into the modern age. Today, the digital revolution weaves a digital tapestry that connects us in ways previously unimaginable, transcending geographical boundaries and fostering a global village of interconnected minds. Amidst the grandeur of nature and the innovations of technology, the human experience is a mosaic of emotions that paint the canvas of our lives. Love, joy, sorrow, and resilience converge to create a symphony of feelings that accompany us through the journey of existence. It is in the embrace of loved ones, the laughter of friends, and the solace of solitude that we find moments of true meaning. Language, the bridge between minds, empowers us to share thoughts, emotions, and ideas with fellow travelers on this cosmic journey. From the verses of ancient poets to the prose of modern storytellers, words have the power to transcend time and touch the souls of generations. Through the written word, we communicate the collective wisdom of humanity, passing down knowledge from one era to the next. The pursuit of knowledge fuels the fires of curiosity that burn within us. Science unfurls the mysteries of the universe, revealing the intricate dance of particles and the cosmic ballet of galaxies. Artistic expression, in its myriad forms, offers a window into the human imagination, capturing the essence of beauty and complexity that define our world. In this grand tapestry of existence, each thread represents a life, each moment a fleeting brushstroke on the canvas of eternity. As we tread the paths of our own narratives, we contribute to the evolving story of humanity, leaving footprints that echo in the corridors of time. The interplay of individual lives and collective destinies weaves a narrative that transcends generations, serving as a testament to the indomitable spirit of the human journey."
]

class User:
    def __init__(self, task_prob, prompt=PROMPTS[0], response_length=300):
        self.task_prob = task_prob
        self.prompt = prompt
        self.response_length = response_length

class Sim:
    def __init__(self, num_iters, base_num_users, base_task_prob):
        self.users = []
        self.client = Client()
        self.num_iters = num_iters
        self.base_num_users = base_num_users
        self.base_task_prob = base_task_prob

        self.req_num = 0

        self.threads = []
        self.exit_event = Event()
        self.lock = Lock()
        self.bg = Thread(target=self.join_background, args=(self.exit_event, ))
        self.bg.start()

    #called every so often to change user number and request probability
    def init_users(self, num_users, base_task_prob):
        self.users = []
        for _ in range(num_users):
            prompt = random.choices(PROMPTS, weights=[0.3, 0.3, 0.3, 0.1], k=1)[0]
            self.users.append(User(task_prob=random.gauss(mu=base_task_prob, sigma=0.1), prompt=prompt))

    def update(self):
        choices = [True, False]
        for user in self.users:
            probs = [user.task_prob, 1 - user.task_prob]
            act = random.choices(choices, weights=probs, k=1)[0]
            if act:
                t = Thread(target=self.client.send_prompt, args=(user.prompt, user.response_length, self.req_num))
                self.req_num += 1
                self.threads.append(t)
                t.start()

    def join_rest(self):
        for t in self.threads:
            t.join()

    def join_background(self, event):
        while not event.is_set():
            for t in self.threads:
                t.join()
            time.sleep(10)

    def deconstruct(self):
        self.client.shutdown_lb()

    def run(self):
        self.client.setup_lb()
        self.client.wait_for_hot()
        for i in range(self.num_iters):
            self.init_users(self.base_num_users + i, self.base_task_prob)
            self.update()
            time.sleep(15)
        self.exit_event.set()
        self.bg.join()
        self.join_rest()
        self.client.get_metrics()
        self.client.metrics.print_metrics()
        self.deconstruct()

def main():
    sim = Sim(num_iters=10, base_num_users=4, base_task_prob=1.0)
    sim.run()

if __name__ == "__main__":
	main()









