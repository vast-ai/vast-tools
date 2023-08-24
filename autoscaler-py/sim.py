import random
import time
from threading import Thread, Lock, Event
from concurrent.futures import ThreadPoolExecutor
from loadbalancer_client import Client
import uuid

MAX_CONCURRENCY = 100

PROMPTS = [ "Yesterday I woke up and I saw that my dog was missing. This made me think that ",
            "I have been thinking a lot about the question of what the best movie of all time is. There are a lot of different ways to approach this question, but for me the most important factor is how exciting it is. With that in mind, I would say the best movie is: ",
            "I hope that one day humans will be able to live on another planet. This planet is great, but there are many issues with it, and it is not clear how long it will last. Other planets are much harder to live on, so it will be hard for other humans to live on them, but in a worst case scenario it would be great to have the option to live on another planet. I think that in order for humans to be able to live on another planet, the following needs to happen: ",
            "In the realm of possibilities, where ideas take shape and dreams find expression, there exists a tapestry of thoughts that intertwine and weave the fabric of our understanding. From the cosmic dance of stars in the night sky to the gentle rustle of leaves in an ancient forest, the universe unfolds its mysteries before our curious gaze. In this vast expanse, the human spirit embarks on a quest for knowledge, driven by an insatiable thirst to unravel the enigma of existence. As we navigate the corridors of time, we are bound by the threads of history that have shaped civilizations and cultures across continents. From the pyramids of Egypt that stand as sentinel monuments to human ingenuity to the intricate temples of Angkor Wat that speak of devotion carved in stone, the echoes of the past reverberate in the present, reminding us of the enduring legacy of our predecessors. The passage of time has ushered in waves of change, ushering in revolutions that have redefined the course of human progress. The clanking gears of the Industrial Revolution gave rise to a new era of mechanization, propelling society into the modern age. Today, the digital revolution weaves a digital tapestry that connects us in ways previously unimaginable, transcending geographical boundaries and fostering a global village of interconnected minds. Amidst the grandeur of nature and the innovations of technology, the human experience is a mosaic of emotions that paint the canvas of our lives. Love, joy, sorrow, and resilience converge to create a symphony of feelings that accompany us through the journey of existence. It is in the embrace of loved ones, the laughter of friends, and the solace of solitude that we find moments of true meaning. Language, the bridge between minds, empowers us to share thoughts, emotions, and ideas with fellow travelers on this cosmic journey. From the verses of ancient poets to the prose of modern storytellers, words have the power to transcend time and touch the souls of generations. Through the written word, we communicate the collective wisdom of humanity, passing down knowledge from one era to the next. The pursuit of knowledge fuels the fires of curiosity that burn within us. Science unfurls the mysteries of the universe, revealing the intricate dance of particles and the cosmic ballet of galaxies. Artistic expression, in its myriad forms, offers a window into the human imagination, capturing the essence of beauty and complexity that define our world. In this grand tapestry of existence, each thread represents a life, each moment a fleeting brushstroke on the canvas of eternity. As we tread the paths of our own narratives, we contribute to the evolving story of humanity, leaving footprints that echo in the corridors of time. The interplay of individual lives and collective destinies weaves a narrative that transcends generations, serving as a testament to the indomitable spirit of the human journey."
]

class User:
    def __init__(self, id, rate, prompt=PROMPTS[0], max_response_length=200):
        self.id = id
        self.rate = rate # prob / sec
        self.prompt = prompt
        self.max_response_length = max_response_length
        self.waiting = False
        self.num_chats = 0
        self.lock = Lock()

class Sim:
    def __init__(self, num_iters, base_num_users, base_rate, etime):
        self.users = []

        self.num_iters = num_iters
        self.num_users = base_num_users
        self.base_rate = base_rate
        self.etime = etime

        self.client = Client()
        self.req_num = 0

        self.threads = []
        self.exit_event = Event()
        self.lock = Lock()
        self.bg = Thread(target=self.join_background, args=(self.exit_event, ))
        self.bg.start()

    def init_users(self):
        users = [] #blank it out
        user_prompts = random.choices(PROMPTS, weights=[0.3, 0.3, 0.3, 0.1], k=self.num_users)
        for up in user_prompts:
            users.append(User(id=uuid.uuid4(), rate=self.base_rate, prompt=up))
        self.users = users

    def send_chat(self, user):
        user.lock.acquire()
        prob = user.rate * self.etime
        if (not(user.waiting) and random.random() <= prob):
            request_str = f"{user.id}-{user.num_chats}"
            prompt = user.prompt
            max_tokens = user.max_response_length
            user.waiting = True
            user.lock.release()
            self.client.send_prompt(prompt, max_tokens, request_str)
            user.lock.acquire()
            user.num_chats += 1
            user.waiting = False
        user.lock.release()

    def update_loop(self):
        with ThreadPoolExecutor(MAX_CONCURRENCY) as e:
            e.map(self.send_chat, self.users)

    def update(self):
        t = Thread(target=self.update_loop)
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
        self.exit_event.set()
        self.bg.join()
        self.join_rest()
        self.client.shutdown_lb()

    def run(self):
        self.client.setup_lb()
        self.client.wait_for_hot()
        self.init_users()

        for i in range(self.num_iters):
            self.update()
            time.sleep(self.etime)

        self.client.get_metrics()
        self.client.metrics.print_metrics()
        self.deconstruct()


def main():
    sim = Sim(num_iters=20, base_num_users=30, base_rate=1.0 * (10 / 60), etime=2.0)
    sim.run()

if __name__ == "__main__":
	main()









