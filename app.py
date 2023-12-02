import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from neo4j import GraphDatabase

load_dotenv()

app = Flask(__name__)

uri = os.getenv("URI")
user = os.getenv("USER")
password = os.getenv("PASSWORD")

driver = GraphDatabase.driver(uri, auth=(user, password),database="neo4j")


def get_employees(tx):
    query = "MATCH (e:Employee)-[:WORKS_IN]-(d:Department) RETURN e,d"
    results = tx.run(query).data()
    employees = [
    {
        'employeeId': result['e']['employeeId'],
        'name': result['e']['name'],
        'lastName': result['e']['lastName'],
        'position': result['e']['position'],
        'department': result['d']['name']
    }
    for result in results
    ]
    return employees

# localhost:5000/employees?sort=position
@app.route('/employees', methods=['GET'])
def get_employees_route():
    sort = request.args.get('sort')
    with driver.session() as session:
        employees = session.execute_read(get_employees)
    if sort:
        employees = sorted(employees, key=lambda k: k[sort])
    response = {'employees': employees}
    return jsonify(response)

def create_employee_node(tx, employee):
    query = (
        """CREATE (e:Employee {employeeId: $employeeId, name: $name, lastName: $lastName, position: $position})-[:WORKS_IN]->(d:Department {name: $department})"""
    )
    tx.run(query, employeeId=employee['employeeId'], name=employee['name'], lastName=employee['lastName'], position=employee['position'],department=employee['department'])

@app.route('/employees', methods=['POST'])
def create_employee_node_route():
    data = request.get_json()
    with driver.session() as session:
        employees = session.write_transaction(get_employees)
    if data['employeeId'] in [employee['employeeId'] for employee in employees]:
        return jsonify({'error': 'Employee already exists'}), 400
    if [key for key in data.keys() if key not in ['employeeId', 'name', 'lastName', 'position','department']]:
        return jsonify({'error': 'Invalid fields'}), 400
    if not all(key in data.keys() for key in ['employeeId', 'name', 'lastName', 'position','department']):
        return jsonify({'error': 'Missing fields'}), 400
    with driver.session() as session:
        session.write_transaction(create_employee_node, data)
    with driver.session() as session:
        session.write_transaction(create_manager_relationship)
    return jsonify(data)

def update_employee_node(tx, employeeId, data, string):
    query = (
        "MATCH (e:Employee {employeeId: $employeeId}) SET " + string[:-2]
    )
    print(string[:-2])
    department= data.get('department')
    name = data.get('name')
    lastName = data.get('lastName')
    position = data.get('position')
    tx.run(query, employeeId=employeeId, name=name, position=position, lastName=lastName,department=department)
    if department!=None:
        query2 = (
            """MATCH (e:Employee {employeeId: $employeeId})-[:WORKS_IN]->(d:Department)
            SET d.name = $department"""
        )
        tx.run(query2, employeeId=employeeId, department=department)

@app.route('/employees/<employeeId>', methods=['PUT'])
def update_employee_route(employeeId):
    data = request.get_json()
    string = ''
    for key in data.keys():
        string += f"e.{key} = ${key}, "
    employeeId=int(employeeId)
    with driver.session() as session:
        employees = session.write_transaction(get_employees)
    if employeeId not in [employee['employeeId'] for employee in employees]:
        return jsonify({'error': 'Employee does not exist'}), 400
    if [key for key in data.keys() if key not in [ 'name', 'lastName', 'position','department']]:
        return jsonify({'error': 'Invalid fields'}), 400
    with driver.session() as session:
        session.write_transaction(update_employee_node,employeeId, data,string)
    with driver.session() as session:
        session.write_transaction(create_manager_relationship)
    return jsonify(data)

def create_manager_relationship(tx):
    query = (
        '''MATCH (manager:Employee {position: 'Manager'})-[:WORKS_IN]->(department)
        MATCH (employee:Employee)-[:WORKS_IN]->(department)
        WHERE NOT employee.position = 'Manager' AND NOT (manager)-[:MANAGES]->(employee)
        CREATE (manager)-[:MANAGES]->(employee)'''
    )
    tx.run(query)

def delete_employee_node(tx, employeeId):
    query = (
        "MATCH (e:Employee {employeeId: $employeeId}) DETACH DELETE e"
    )
    tx.run(query, employeeId=employeeId)

@app.route('/employees/<employeeId>', methods=['DELETE'])
def delete_employee_route(employeeId):
    employeeId=int(employeeId)
    with driver.session() as session:
        employees = session.write_transaction(get_employees)
    if employeeId not in [employee['employeeId'] for employee in employees]:
        return jsonify({'error': 'Employee does not exist'}), 400
    departament = [employee['department'] for employee in employees if employee['employeeId'] == employeeId][0]
    if len([employee for employee in employees if employee['department'] == departament and employee['position'] == 'Manager']) == 1:
        return jsonify({'error': 'Cannot delete the only manager'}), 400
    with driver.session() as session:
        session.write_transaction(delete_employee_node,employeeId)
    return jsonify({'message': 'Employee deleted'})

def get_subordinates(tx, employeeId):
    query = """
        MATCH (e:Employee {employeeId: $employeeId})-[:MANAGES]->(s:Employee)
        RETURN s
    """
    results = tx.run(query, employeeId=employeeId).data()
    subordinates = [{'employeeId': result['s']['employeeId'], 'name': result['s']['name']} for result in results]
    return subordinates

@app.route('/employees/<employeeId>/subordinates', methods=['GET'])
def get_subordinates_route(employeeId):
    employeeId = int(employeeId)
    with driver.session() as session:
        subordinates = session.read_transaction(get_subordinates, employeeId)
    return jsonify({'subordinates': subordinates})

@app.route('/employees/<employeeId>/department', methods=['GET'])
def get_department_route(employeeId):
    data={}
    count=0
    employeeId = int(employeeId)
    with driver.session() as session:
        employees = session.execute_read(get_employees)
    for employee in employees:
        if employee['employeeId']==employeeId:
            data['department']=employee['department']
        count+=1
    for employee in employees:
        if employee['department']==data['department'] and employee['position']=='Manager':
            data['manager']=employee['name']+' '+employee['lastName']
    data['pracownicy']=count
    if employeeId not in [employee['employeeId'] for employee in employees]:
        return jsonify({'error': 'Employee does not exist'}), 400
    return jsonify(data)


@app.route('/departments', methods=['GET'])
def get_departments_route():
    data={}
    sort_by = request.args.get('sort')
    with driver.session() as session:
        employees = session.execute_read(get_employees)
    departments = list(set([employee['department'] for employee in employees]))
    for department in departments:
        data[department] = {
            'manager': [employee['name']+' '+employee['lastName'] for employee in employees if employee['department'] == department and employee['position'] == 'Manager'][0],
            'employees': len([employee for employee in employees if employee['department'] == department]),
        }
    if sort_by == 'manager':
        data = dict(sorted(data.items(), key=lambda item: item[1]['manager']))
    elif sort_by == 'employees':
        data = dict(sorted(data.items(), key=lambda item: item[1]['employees']))
    elif sort_by == 'name':
        data = dict(sorted(data.items(), key=lambda item: item[0]))

    return jsonify(data)

@app.route('/departments/<department>/employees', methods=['GET'])
def get_employees_by_department_route(department):
    department = department.replace('_', ' ')
    with driver.session() as session:
        employees = session.execute_read(get_employees)
    employees = [employee for employee in employees if employee['department'] == department]
    return jsonify({'employees': employees})

if __name__ == '__main__':
    app.run()
    