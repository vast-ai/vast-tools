for X in {1..10}
do
echo $X
curl 127.0.0.1:5000/generate_stream  -X POST  -d '{"inputs":"What is Deep Learning?","parameters":{"max_new_tokens":256}}' -H 'Content-Type: application/json' -N &
done
