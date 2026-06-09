def calculate_average(numbers):
    total = 0
    for number in numbers:
        total += number
    average = total / len(numbers)
    return average

numbers = []
result = calculate_average(numbers)
print("The average is:", result)