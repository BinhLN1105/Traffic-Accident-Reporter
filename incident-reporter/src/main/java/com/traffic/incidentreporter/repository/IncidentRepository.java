package com.traffic.incidentreporter.repository;

import com.traffic.incidentreporter.entity.Incident;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface IncidentRepository extends JpaRepository<Incident, Long> {
    List<Incident> findTop10ByOrderByTimestampDesc();

    @org.springframework.data.jpa.repository.Query(value = "SELECT min(t1.id + 1) FROM incidents t1 LEFT JOIN incidents t2 ON t1.id + 1 = t2.id WHERE t2.id IS NULL", nativeQuery = true)
    Long findNextAvailableId();
    
    @org.springframework.data.jpa.repository.Query(value = "SELECT max(id) FROM incidents", nativeQuery = true)
    Long findMaxId();

    boolean existsById(Long id);
}
