for X in {1..3}
do
echo $X
curl 185.120.146.218:40258/generate_stream -X POST  -d '{"token": "22e9c620e8c500dbf3ac880fa1b54242ab51a5420c1bd2af5d2450b489d46731", "inputs":"What is Deep Learning?","parameters":{"max_new_tokens":256}}' -H 'Content-Type: application/json' -N &
done
